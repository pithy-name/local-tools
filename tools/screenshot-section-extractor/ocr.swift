// Apple Vision OCR / crop helper for two-column assessment screenshots.
// Crops a normalized region (top-left origin) and upscales it. By default it
// runs accurate text recognition and prints TSV: xGlobal \t yGlobal \t text
// (both normalized to the FULL image, top-left origin, so callers can sort
// top->bottom). With --save <out.png> it instead writes the cropped+scaled
// image as PNG (for visual verification) and prints nothing.
//
// Oversized crops are capped (Vision downsamples large images, which clips/drops
// text), so the effective scale never produces a dimension beyond MAX_DIM.
//
// Usage:
//   swift ocr.swift <png> <x0> <y0> <x1> <y1> <scale> [--save <out.png>]
//
// Local-only: uses the on-device Vision framework, no network. macOS only.

import Foundation
import Vision
import AppKit

let a = CommandLine.arguments
guard a.count >= 7 else {
    FileHandle.standardError.write("usage: <png> x0 y0 x1 y1 scale [--save out.png]\n".data(using:.utf8)!)
    exit(2)
}
let path = a[1]
let x0 = Double(a[2])!, y0 = Double(a[3])!, x1 = Double(a[4])!, y1 = Double(a[5])!
let reqScale = Double(a[6])!
var savePath: String? = nil
if a.count >= 9, a[7] == "--save" { savePath = a[8] }

let MAX_DIM = 8000.0   // keep the scaled crop within Vision's comfortable range

guard let img = NSImage(contentsOfFile: path),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("load fail: \(path)\n".data(using:.utf8)!); exit(1)
}
let W = Double(cg.width), H = Double(cg.height)
let rect = CGRect(x: x0*W, y: y0*H, width: (x1-x0)*W, height: (y1-y0)*H)
guard let crop = cg.cropping(to: rect) else { exit(1) }

let cropW = Double(crop.width), cropH = Double(crop.height)
let scale = min(reqScale, MAX_DIM/cropW, MAX_DIM/cropH)
let cw = Int(cropW*scale), ch = Int(cropH*scale)
let cs = CGColorSpaceCreateDeviceRGB()
guard let ctx = CGContext(data: nil, width: cw, height: ch, bitsPerComponent: 8,
        bytesPerRow: 0, space: cs,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { exit(1) }
ctx.interpolationQuality = .high
ctx.draw(crop, in: CGRect(x: 0, y: 0, width: cw, height: ch))
guard let scaled = ctx.makeImage() else { exit(1) }

if let out = savePath {
    let rep = NSBitmapImageRep(cgImage: scaled)
    guard let data = rep.representation(using: .png, properties: [:]) else { exit(1) }
    try? data.write(to: URL(fileURLWithPath: out))
    exit(0)
}

let req = VNRecognizeTextRequest { r, _ in
    guard let obs = r.results as? [VNRecognizedTextObservation] else { return }
    for o in obs {
        guard let t = o.topCandidates(1).first else { continue }
        let b = o.boundingBox                       // Vision: bottom-left origin
        let yTopLocal = 1.0 - b.maxY                // local top within crop (0 = top)
        let yGlobal = y0 + yTopLocal * (y1 - y0)
        let xGlobal = x0 + b.minX * (x1 - x0)
        print("\(String(format:"%.4f",xGlobal))\t\(String(format:"%.4f",yGlobal))\t\(t.string)")
    }
}
req.recognitionLevel = .accurate
req.usesLanguageCorrection = true
let handler = VNImageRequestHandler(cgImage: scaled, options: [:])
try? handler.perform([req])
