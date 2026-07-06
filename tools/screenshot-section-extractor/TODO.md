# TODO — before publishing / moving to the public repo

Work through these when relocating this toolkit into its public repository.

## Move safeguards (do NOT skip — these prevent leaks)

- [ ] **Carry this `.gitignore` into the destination repo** (or merge its rules).
      It must keep ignoring `.env` and the compiled `ocr` binary.
- [ ] **Do not copy your local `.env` or the `ocr` binary into the new repo.**
      They are secret / build artifacts. The real `.env` holds your tuned values;
      the `ocr` binary is a local arm64 build. Rebuild it there with
      `swiftc -O ocr.swift -o ocr`.
- [ ] **Keep the `demo/` folder intact and beside the README.** The README's
      relative links (`demo/sample-assessment-2023-02.png`, `demo/sample-output.md`)
      break if the folder is split or moved.

## Before going public

- [ ] **Fill the `LICENSE` copyright holder** — currently `pithy-name`. Replace
      with your chosen public name/handle.
- [ ] (optional) Voice-check the `README.md` if publishing under your name —
      it is currently in a generic technical-README voice.
