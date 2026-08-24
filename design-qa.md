# Design QA

- Source visual truth: `/Users/kris/.codex/generated_images/01a031d7-f5a8-7361-8a03-19902d577760/exec-85bd4859-42e3-4b0c-8d23-2f0dff3c9cea.png`
- Implementation capture: `/Users/kris/workspace/erp/implementation-login-blocked.png`
- Browser viewport: 393 × 852 CSS px, device scale factor 1
- Source pixels: 853 × 1844; implementation pixels: 393 × 852
- Intended state: confirmed production flow card, cutting material issue step
- Captured state: login screen

**Findings**

- [P0] The protected task screen could not be captured.
  - Location: mobile H5 route for the scanned production flow card.
  - Evidence: the local preview redirects to the login screen; no authenticated local browser session was available.
  - Impact: the implementation and selected reference cannot be put into a same-state visual comparison, so typography, spacing, colors, material imagery, copy, and interaction states cannot receive a valid visual pass.
  - Fix: authenticate in the local preview with a cutting-leader account, scan/open a confirmed flow card, and recapture at 393 × 852.

**Full-view comparison evidence**

- The selected source image was opened and inspected.
- The browser-rendered implementation was captured, but it represents the login state and therefore is not comparable to the task state.

**Focused region comparison evidence**

- Not performed because the implementation task state is behind authentication.

**Primary interactions tested**

- H5 application boot and login-route rendering.
- Production H5 build.
- Server-side cutting workflow regression suite.
- Task interactions were not browser-tested because authentication blocked the target route.

**Console errors checked**

- No browser console errors on application boot/login screen.

**Comparison history**

- Initial pass: blocked by authentication before the target screen could render. No visual fixes were made from an invalid cross-state comparison.

**Implementation checklist**

- Log in with a cutting-leader account in the local preview.
- Open a confirmed production flow card.
- Verify quantity input, automatic material calculation, over-plan validation, issue submission, start-cutting gate, cutting report, success dialog, and return-home behavior.
- Capture and compare the task screen against the selected visual.

final result: blocked
