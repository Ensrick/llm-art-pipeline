# The review process

This is for every agent that builds or changes a model, outfit, prop or animation, and for
whoever coordinates them. It sets the order of work and the review gates. For how to build motion
and gear, see the other guides:

- [ANIMATION.md](ANIMATION.md) - briefs, edit words, retargeting, checks.
- [GEAR.md](GEAR.md) - sockets, loadouts, grips.

## 1. The rule

**Make changes in 3D, where a round of changes costs minutes. Export to your final format (game
sprites, a baked texture, whatever is slow to produce) once, after the project owner has approved
the 3D clips.**

It is tempting to skip the 3D review and get art into the target engine sooner, tolerating small
mistakes that are hard to see at final scale. In practice this costs more time than it saves:
every correction still needs another full export, plus another round of checking it in the real
engine. Measure your own pipeline once - re-rendering a final asset for every small 3D tweak is
almost always far more expensive than reviewing the tweak in 3D first. If final export is cheap
for your project, this rule matters less; if it is slow (baking, atlas packing, a game import
step), it matters a lot.

## 2. The loop

1. **Brief.** Whoever is coordinating repeats the request back as a numbered list, quoting the
   project owner's own words. Each confirmed decision is written down (a design doc, an issue,
   whatever your project's source of truth is) in the same turn. Each unit or asset has one owner.
2. **Build in 3D.** The owner changes the model, outfit or motion. Put a new look behind a flag
   (an environment variable or a boolean in the build script) so the currently-shipping look keeps
   rendering unchanged until it's approved.
3. **Run the automatic checks** before anyone sees the result (see [ANIMATION.md](ANIMATION.md)
   and [GEAR.md](GEAR.md)). Report numbers, not just pass or fail.
4. **Send the review package** (section 3). Open every image and clip yourself before sending it
   on, rather than trusting that a render succeeded.
5. **The verdict**, item by item: approve, change (with edit words - see ANIMATION.md section 3),
   or defer. Whether to fix a small flaw or live with it is decided here, in 3D, never after the
   final export.
6. **Repeat steps 2 to 5** until approved. Each round is one batch of edits.
7. **Freeze.** The owner commits, then tells whoever runs the final export that the inputs are
   frozen as of that commit (section 5).
8. **Final render/export**, from the frozen commit only.
9. **Install / integrate**, with a receipt (a log line, a commit, whatever lets you point at what
   changed) and a rollback path. Make this step art-only when only the final export changed.
10. **Check the real result.** At this stage expect only problems that show at final scale:
    readability, colour under real lighting, timing against real game logic. If a shape or pose
    problem turns up here, the 3D review missed it - write down why, in the unit's own notes, so
    the next review catches that class of problem earlier.

## 3. The review package

Send only what changed in this round, in files small enough to open on a phone.

- **Animation clips.** Each changed action as a looping GIF (under about 5 MB - see
  `tools/frames_to_gif.py`) or an MP4 (`tools/review_render.py`), at real playback speed.
  - One view from the angle your final render actually uses, so the clip reads the way the
    shipped result will.
  - One closer three-quarter view where the change is easy to see.
  - Deaths and falls: hold on the final pose for a second.
- **Turnaround** for any model or outfit change: front, side, back and three-quarter stills, or a
  slow turning GIF.
- **Before and after**, side by side, with the same camera and frames.
- **Options A and B**, one line each on the difference, whenever the request can be read more than
  one way (section 4).
- **Proof frame:** one still that answers the specific complaint (for example, a front view that
  shows which way a carried object faces).
- **A scale strip**, only when colour, shine or silhouette is the question: the asset at native
  export size and at 3-4x.
- **Team/variant colour**, when a tinted part changed: a sheet showing every variant's tint.
- **Renderer choice.** Motion-only clips can use a fast viewport renderer. Material, metal and
  shine must be reviewed through your actual shading path, because a fast preview renderer
  commonly ignores metallic/shine parameters that your final renderer honours.
- **changes.md**, 5 lines at most: what changed, the check numbers, and what is deferred.
- Save review files under a per-unit `review/` folder, named `<unit>_<change>_r<round>.gif`.
- If a later change makes a review file wrong, re-render it or say so in the unit's notes. A stale
  review sheet that still shows an old part after a later change is a common, avoidable confusion.

## 4. Asking and answering precisely

- **Do the smallest change that meets the request.** Asked to remove one small part of a helmet,
  it is easy to accidentally remove the whole visor instead. When a request is unclear, show
  options A and B instead of guessing.
- **Hide only what the new gear covers.** Fitting a full suit of armour that hides the whole body
  will leave a separately-attached helmet looking empty if it was relying on the head still being
  there. Keep what the new item doesn't actually cover.
- **Check which way things face, early.** "It's on backwards" complaints after a full render are
  expensive. A single front-view proof frame catches this in minutes.
- **Show a visible change every round.** If a project owner can't see anything different, they
  can't direct the next round. If a round has nothing visible to show, say so plainly and say why.
- **Never describe how something looks from data values** such as RGB numbers or mesh names. Show
  the image.
- **Keep confirmed decisions separate from open questions.** A design doc (or wherever decisions
  live) holds only what's confirmed; open questions stay in a tracker/issue list.

## 5. Handoffs and freezes

- **A freeze/handoff message contains:** the commit; what changed; how to render it (the actions,
  slots, process count, flags); which input files to record; the check results; what is deferred.
- **Inputs stay frozen from the handoff until the final build is confirmed installed**, not just
  until the handoff message is sent. An edit landing seconds after a handoff, or a shared recipe
  changing mid-render, can make a multi-hour render come out stale without anyone intending it.
- **Work on the next change in a separate branch or worktree**, or hold the edit until the current
  build is confirmed done. A build system that checks recorded inputs against the working tree
  will treat an uncommitted edit as making its finished output stale.
- **Shared recipes invalidate every build made from them.** A shared material or shared rig change
  can silently block or invalidate builds that already looked finished. Land shared recipe changes
  before a build starts, never during one.
- **A new look folds in fixes already shipped by someone else.** It never reverts them - check what
  the current shipped state already includes before starting from an older baseline.

## 6. Messages between agents

- **A message to a busy agent arrives only when that agent goes idle.** That can be a long time
  later. Don't assume a message has been seen just because it was sent.
- **Confirm delivery of anything time-sensitive** by checking the recipient actually acted on it
  (for example, searching its transcript or output for the commit hash you sent).
- **When a correction changes what a busy agent is building, stop it before sending the
  correction**, so the correction becomes its next instruction instead of arriving after it has
  already finished the wrong thing.
  - Only stop an agent while its current command is just waiting on something.
  - Stopping ends that command's process, and anything else that was running in the same command
    (a render, for instance) ends with it.
- **Write decisions to the shared tracker in the same step as sending the message about them.** An
  agent that polls the tracker can otherwise act on a decision before the message announcing it
  has even arrived - which is usually fine, but only if the tracker and the message agree.
- **Give a one-line status report at every stage:** handoff sent, build started, handed over,
  installed. This is cheap and makes the whole pipeline's state visible without anyone having to
  ask.

## 7. Working alongside another agent or team on the same project

If more than one agent or tool touches the same repository and the same live build at once:

- **Never edit files owned by the other agent/team.** Agree on ownership boundaries (by
  directory, or by an explicit list) up front.
- **A build from the other side can move shared output folders.** Verify an output folder is what
  you expect before using it, rather than assuming it's untouched since you last looked.
- **Read the actual installed-state file before assuming what is currently installed.** Version
  numbers get reused across a project's history more often than you'd expect, so a version number
  alone is not proof of what's live.

## 8. Lessons from gear and motion, worth checking for on any project

- **Metal:**
  - A believable metal usually wants high metallic with low-to-moderate roughness (a few sharp
    glints) or slightly higher roughness (no clipped/blown-out highlight pixels) - tune both
    together, not metallic alone.
  - Heavier, duller armour types often need metallic and roughness both toned down further so they
    don't blow out to flat white blocks at small/distant scale.
  - Count blown-out pixels at the scale the asset will actually be seen at, not at close-up scale.
- **Team/variant colour:** a colour-by-mask material needs its own dedicated mask channel or
  region. Check the mask with an actual tint applied, not just in the un-tinted base colour - a
  static preview image will show the masked region as untinted grey, which is easy to mistake for
  a broken mask.
- **Held weapons and tools:**
  - Solve the hand's pose from the held object's geometry, not the other way round. Forcing a hand
    into a generic "holding" pose without checking against the actual object's shape can bend the
    wrist far past a natural range without anyone noticing until it's pointed out.
  - Check wrist bend and the held object's clearance from the hand/arm before any review, not
    after.
- **Grips:** a closed hand generally only passes a grip check cleanly on a round shaft near a
  specific, fairly narrow diameter (tune this for your own rig; three centimetres or so is a
  common starting point for a human-scale fist). Remove hidden inner faces from layered grip
  geometry (leather wraps, bindings) - they cost nothing visually and can confuse collision/overlap
  checks.
- **Cloth** (banners, cloaks, capes, barding):
  - Check faster movement states (a run, not just idle/walk) for cloth simulated with wind that
    wraps the wrong way at speed.
  - Add a collider to keep simulated cloth on the correct side of the body.
  - Use a mesh fine enough that it can't visibly cut through a pole or a limb it should drape
    around.
- **Deaths and lying/prone frames:** check gear against the body once it's on the ground, not just
  standing. Skirts, straps and anything slung on the back are the usual offenders for clipping.
- **Scale:** scale models uniformly. A non-uniform (for example height-only) scale applied to a
  rig will stretch any rigid prop that's parented to a rotating bone on that rig - a real example
  from this kind of setup turned a prop about 10% too long in certain poses purely from an
  inherited non-uniform scale, with no error anywhere until someone measured it.

## 9. Licences

**No downloaded material goes into a project until its licence is recorded and verified.** If
you're not sure a downloaded asset is actually free to use the way you intend, don't use it until
you've confirmed it from the source page, the site's API, or a licence file included in the
download. An unverifiable licence means the asset doesn't get used - not "used for now, verify
later."

- Register every downloaded model before it ships: what it is, who made it, its licence, and
  where it came from. `tools/prepare_downloaded_model.py` bakes this onto the prepared result
  automatically, so it travels with the asset instead of living only in a commit message; keep a
  project-wide registry (a JSON file, a CREDITS document, whatever fits your project) too.
- Downloaded source files themselves are not committed - only what's built from them ships. See
  `tools/prepare_downloaded_model.py`'s docstring for why, and how it keeps the source and the
  prepared result separate.
- A model with an unverified or restrictive licence stays out of anything that ships, even if it's
  fine for your own private reference. Two situations worth specifically checking for:
  - a licence line you can't actually confirm from the source (don't assume the most permissive
    reading);
  - a share-alike licence, which can conflict with unrelated, more permissively-licensed assets
    shown in the same shipped output.

## 10. Checklist for each round

- [ ] The request is repeated back as a numbered list, and confirmed decisions are written down
      somewhere durable.
- [ ] The change is behind a flag, and the currently-shipping look still renders unchanged.
- [ ] The checks are run and their numbers recorded: intersections/crossings, joint bend limits,
      grip quality, ground clearance, loop seam, and any colour/mask checks that apply.
- [ ] The review package has clips from the real camera angle and a close view, a before-and-after,
      a proof frame for the specific complaint, and a short changes note.
- [ ] Every file has actually been opened and looked at before it goes to the project owner.
- [ ] The project owner has approved it in 3D before any freeze/handoff.
- [ ] The freeze/handoff message is complete and its inputs stay frozen until the build is
      confirmed installed.
- [ ] Follow-up work happens in a separate branch/worktree, and any now-stale review files are
      re-rendered or noted as stale.
