# Room monitoring and review scoring

Teacher → Live Monitor uses the selected exam's saved CSV assignments. The
seating plan shows student names and registration numbers, distinguishes empty
seats, and displays the saved classroom polygons when available. REST live
reconciliation refreshes it even if Socket.IO misses a change.

## One fixed camera per classroom

1. Upload a fully resolved seating CSV. Invalid replacements preserve the
   previous map. Seat numbers must fit the configured classroom capacity.
2. Open the classroom camera. Choose each CSV seat and draw a separate camera
   region containing that student's face and desk. Map every active assignment;
   camera regions must not overlap. A floor plan is not automatically a camera
   projection, so the application never guesses that correspondence.
   Valid camera regions are remembered in the current browser tab for the same
   camera, image dimensions, exam, and roster. Review them before reusing them.
   No camera photos are stored in browser storage.
3. Begin room monitoring. Ask students to face forward and select **Set neutral
   for all seats**. Each seat calibrates independently. Faces need at least
   60 × 70 captured pixels; enlarging a blurry face cannot establish valid angles.
4. Inspecting a seat only highlights that camera region. Detection attribution
   continues across the entire mapped room. Keep the camera fixed. Stop and
   remap it after changing the position, lens, resolution, or seating roster.

The hosted service bounds each room to 64 mapped seats. Face estimation uses
independent native seat crops, with one shared MediaPipe IMAGE inference source
and separate calibrated rotation/timing state per seat. This avoids short-range
face detection losing faces in a wide-room image and avoids VIDEO tracking
carrying one seat's face into another crop. Multiple faces, unclear faces, and
faces straddling seat regions cannot establish an attributed head warning.

Object inference scans one native seat crop per request to bound CPU load. A
seat with an object remains selected internally for three recognitions, then
scanning continues. Unchecked seats receive neither fabricated detections nor
fabricated absences. A scan explicitly reports the seat and inference duration.
An edge-clipped object cannot establish ownership. Saved snapshots contain only
the implicated student's camera region.

This is not a guarantee of simultaneous real-time object coverage across a
large hall on a single shared CPU. Measure the scan interval, image detail,
lighting, and occlusion with the installed room camera before relying on it.
GPU processing or additional camera coverage may be required for a large room.

## Scoring policy

These are review signal strengths, not probabilities of cheating. Raw neural
recognition confidence remains unchanged in the camera overlays.

- Phones require model confidence ≥ .50; books require ≥ .60. Confidence below
  these verification floors never qualifies, even with high admin sensitivity.
- A verified object maps to policy strength .80 at its class floor, increasing
  linearly to 1.00 at model confidence 1.00. Admin thresholds use this scale.
- Three consecutive recognitions of the same track must span at least three
  seconds. Missing recognition, a gap over 30 seconds, or stricter thresholds
  that invalidate previous scores resets that track's confirmation history.
- Head pose requires neutral calibration and a continuous violation lasting
  two seconds: absolute yaw > 30°, or relative pitch < −20°, with hysteresis.
  Sustained, server-image-verified head pose supplies strength .85. Missing,
  ambiguous, unreliable, or interrupted face observations reset the timer.
- The composite is the weighted average of present qualifying signals. Without
  configured weights it is the strongest signal. Empty signals score zero;
  explicitly zero-weight signals cannot independently trigger. Scores and
  weights must be finite and in their valid ranges. Case creation requires
  composite ≥ .75.
- Each seat/signal has a 30-second atomic cooldown. A combined object/head
  observation cannot bypass the head-only cooldown. Newly qualifying signals
  can create their own case while older signals remain in cooldown.

The older internal frame worker also advances missing signals as zero, rejects
duplicate frame indices, and resets interrupted streams. Its 18-frame window
requires 11 qualifying observations. The strength is averaged across qualifying
observations; missing frames control persistence rather than diluting strength.

## Integrity and review

Exam camera routes require the assigned, active Teacher. They recheck exam
status, account access, and exact seat attribution after inference and before
saving. A CSV roster change stops the room run. Personal equipment checks never
save exam cases. Private evidence enters the existing Teacher/HOD review flow;
the Admin, Exam Controller, and Student retain their established scoped access.
No detection automatically applies a penalty.

Case, detection, audit, and notification records commit together. A subsequent
socket/MQTT delivery failure cannot remove the committed snapshot or release its
cooldown. The website's authorized REST reconciliation recovers missed live
messages. Failed uncommitted uploads release their owned cooldown claims for
retry and report an error in the camera panel.
