"""All tunable numbers in one place.

Units: "BL" = body lengths, where one body length is the fighter's torso length
(shoulder-midpoint to hip-midpoint) in pixels. Normalising by it makes every
threshold independent of resolution, camera zoom and how far the fighter is
from the camera.
"""
from dataclasses import dataclass, field


@dataclass
class Config:
    # ---- Stage 1: pose extraction -------------------------------------------
    pose_model: str = "yolo11m-pose.pt"  # yolo11x-pose.pt = slower but more accurate
    imgsz: int = 960                     # inference size; 1280 helps on wide shots
    det_conf: float = 0.25
    device: str | None = None            # None -> mps if available, else cpu
    batch: int = 8

    # ---- Detection filtering --------------------------------------------------
    kp_conf: float = 0.35                # keypoint considered visible above this
    min_visible_kps: int = 6
    min_box_area: float = 0.004          # fraction of frame area (drops the crowd)

    # ---- Two-fighter identity tracking ----------------------------------------
    app_weight: float = 0.55             # appearance (shorts/torso colour) cost weight
    pos_weight: float = 0.25             # predicted-position cost weight
    iou_weight: float = 0.20             # box-overlap cost weight
    match_gate: float = 0.70             # reject assignments costlier than this
    app_gate: float = 0.75               # max appearance distance while tracking
    app_gate_reacquire: float = 0.75     # when re-finding a lost fighter / after a cut
    #   (measured on real footage: the same fighter after a camera change scores 0.5-0.7;
    #    the referee slot + relative cost, not this gate, is what rejects wrong people)
    reacquire_after_s: float = 0.5       # lost longer than this -> appearance-only matching
    template_lr: float = 0.03            # how fast the appearance template adapts
    jump_confirm_frames: int = 4         # a sudden jump to a far-away box must persist this many frames
    weak_match: float = 0.60             # appearance distance above this is a weak match...
    ambiguous_margin: float = 0.10       # ...and must beat the other fighter by this much
    steal_margin: float = 0.25           # appearance margin needed to take a box the other fighter is tracking
    min_shorts_px: int = 300             # shorts region must be this big (and >=60% in frame) to be used
    adapt_max_dist: float = 0.6          # only adapt on confident matches...
    adapt_margin: float = 0.15           # ...that look clearly more like this identity than any other
    min_skin_auto_init: float = 0.20     # auto-init prefers shirtless people (not the referee)
    app_contrast: float = 1.0            # weight of "more like me than like the other fighter"
    floating_bottom: float = 0.90        # no legs visible AND box ends above this frac of height => spectator
    min_rel_size: float = 0.50           # sqrt(area) below this frac of the biggest person => spectator
    min_bottom: float = 0.50             # box ending above this frac of frame height => spectator
    max_noncand_s: float = 0.5           # a slot may follow a spectator-looking box (occluded fighter) this long

    # ---- Keypoint smoothing (One Euro filter) ---------------------------------
    euro_min_cutoff: float = 1.2
    euro_beta: float = 0.015

    # ---- Movement signals -----------------------------------------------------
    advance_thresh: float = 0.35         # BL/s toward opponent to count as advancing
    engage_range: float = 6.0            # BL between fighters; beyond this nothing is "engaged"

    # ---- Strike attempt detection -----------------------------------------------
    punch_speed: float = 5.0             # BL/s, wrist relative to its shoulder
    kick_speed: float = 4.5              # BL/s, ankle relative to its hip
    arm_extension: float = 0.80          # |shoulder->wrist| / (upper arm + forearm)
    leg_extension: float = 0.82
    kick_raise: float = 0.35             # kicking ankle must be this many BL above the other
    toward_cos: float = 0.15             # strike must travel toward the opponent
    strike_range: float = 4.0            # BL; ignore "strikes" thrown from far away
    max_burst_s: float = 0.45
    hand_refractory_s: float = 0.15
    kick_refractory_s: float = 0.5
    speed_cap: float = 45.0              # BL/s; faster = keypoint glitch, ignore
    head_radius: float = 0.55            # BL; wrist this close to head centre = "on target?"

    # ---- Posture / drops ----------------------------------------------------------
    down_angle: float = 58.0             # torso degrees from vertical => down
    up_angle: float = 38.0
    down_hold_s: float = 0.20
    up_hold_s: float = 0.50
    kd_window_s: float = 1.5             # on-target strike this recently before a drop => possible KD
    takedown_ctrl_s: float = 0.5         # top position must be held this long to credit a takedown
    sudden_drop: float = 1.8             # BL/s downward hip speed counts as "sudden"

    # ---- Momentum score -------------------------------------------------------
    half_life_s: float = 20.0            # older actions fade; 20 s half-life
    prior: float = 4.0                   # pseudo-points each side (keeps early numbers sane)
    display_tau_s: float = 0.8           # smoothing of the displayed percentage
    weights: dict = field(default_factory=lambda: {
        "punch": 1.0,          # per punch attempt
        "kick": 1.3,           # per kick attempt
        "on_target": 1.5,      # bonus when the strike ends on the opponent's head/body (proximity)
        "pressure": 0.5,       # per second per BL/s advanced toward the opponent
        "retreat_gift": 0.25,  # per second per BL/s the OPPONENT retreats
        "activity": 0.08,      # per second per unit of limb activity
        "control": 0.8,        # per second standing over / on top of a downed opponent
        "takedown": 3.0,       # opponent went down in close contact
        "knockdown": 10.0,     # opponent dropped suddenly right after an on-target strike
    })
