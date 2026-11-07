# Tasks: scene seam continuity

- [ ] 1. Confirm the root cause
  - [ ] 1.1 Trace how the router maps the `image` field for the selected video model
  - [ ] 1.2 Measure `media.seam_gap` on one seeded clip
  - [ ] 1.3 Record the finding in `design.md` and choose a fix
- [ ] 2. Add a failing test that reproduces the confirmed cause
- [ ] 3. Implement the chosen fix in the provider client or engine
- [ ] 4. Show the remaining seam gap on the scene
  - [ ] 4.1 Return the status from the API
  - [ ] 4.2 Show it in the project editor, with translations in `ui/src/i18n.jsx`
  - [ ] 4.3 Rebuild `ui/dist`
- [ ] 5. Add tests for the unchanged behavior listed in `bugfix.md`
- [ ] 6. Run the backend tests and render one real project to check the seams
