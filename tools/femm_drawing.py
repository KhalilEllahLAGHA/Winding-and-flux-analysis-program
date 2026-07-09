"""Shared FEMM geometry helpers used by the standalone simulation tools.

Extracted from the previously duplicated drawing code in ``flux_run.py``
and ``validation_a_vide.py``.
"""

import math

import femm

# Circles are approximated with small arcs of this angular size so slot
# openings can be skipped cleanly.
CIRCLE_ARC_STEP_DEG = 5


def draw_complete_circle(radius):
    """Draw a full circle from four quarter arcs."""
    femm.mi_addnode(radius, 0)
    femm.mi_addnode(0, radius)
    femm.mi_addnode(-radius, 0)
    femm.mi_addnode(0, -radius)

    femm.mi_addarc(radius, 0, 0, radius, 90, 1)
    femm.mi_addarc(0, radius, -radius, 0, 90, 1)
    femm.mi_addarc(-radius, 0, 0, -radius, 90, 1)
    femm.mi_addarc(0, -radius, radius, 0, 90, 1)


def draw_circle(radius, n_slots=0, slot_pitch=0.0, slot_angle=0.0,
                skip_slots=False):
    """Draw a circle from small arcs, optionally leaving slot openings."""
    step = CIRCLE_ARC_STEP_DEG
    for start_angle in (0, 90, 180, 270):
        for angle in range(start_angle, start_angle + 90, step):
            if skip_slots and _arc_intersects_slot(angle, angle + step,
                                                   n_slots, slot_pitch,
                                                   slot_angle):
                continue

            x1 = radius * math.cos(math.radians(angle))
            y1 = radius * math.sin(math.radians(angle))
            x2 = radius * math.cos(math.radians(angle + step))
            y2 = radius * math.sin(math.radians(angle + step))
            femm.mi_addnode(x1, y1)
            femm.mi_addnode(x2, y2)
            femm.mi_addarc(x1, y1, x2, y2, step, 1)


def _arc_intersects_slot(arc_start, arc_end, n_slots, slot_pitch, slot_angle):
    for slot_num in range(int(n_slots)):
        slot_start = slot_num * slot_pitch
        slot_end = slot_start + slot_angle
        if any(slot_start <= a <= slot_end for a in (arc_start, arc_end)):
            return True
    return False


def draw_magnet(start_angle, arc_width, r_inner, r_outer, direction=1,
                magnet_strength=1.2):
    """Draw one arc-shaped magnet with radial magnetization.

    direction=+1 magnetizes outward (north pole), -1 inward (south pole).
    """
    start_rad = math.radians(start_angle)
    width_rad = math.radians(arc_width)

    x1 = r_outer * math.cos(start_rad)
    y1 = r_outer * math.sin(start_rad)
    x2 = r_outer * math.cos(start_rad + width_rad)
    y2 = r_outer * math.sin(start_rad + width_rad)
    x3 = r_inner * math.cos(start_rad + width_rad)
    y3 = r_inner * math.sin(start_rad + width_rad)
    x4 = r_inner * math.cos(start_rad)
    y4 = r_inner * math.sin(start_rad)

    femm.mi_addnode(x1, y1)
    femm.mi_addnode(x2, y2)
    femm.mi_addnode(x3, y3)
    femm.mi_addnode(x4, y4)

    femm.mi_addarc(x1, y1, x2, y2, arc_width, 1)
    femm.mi_addarc(x4, y4, x3, y3, arc_width, 1)
    femm.mi_addsegment(x2, y2, x3, y3)
    femm.mi_addsegment(x4, y4, x1, y1)

    angle_mid = start_angle + arc_width / 2
    r_mid = (r_inner + r_outer) / 2
    lx = r_mid * math.cos(math.radians(angle_mid))
    ly = r_mid * math.sin(math.radians(angle_mid))

    femm.mi_addblocklabel(lx, ly)
    femm.mi_selectlabel(lx, ly)

    magnetization_angle = angle_mid if direction > 0 else (angle_mid + 180) % 360
    femm.mi_setblockprop("NdFeB", 0, 1, "<None>", magnetization_angle, 0,
                         magnet_strength)
    femm.mi_clearselected()


def draw_rotor_magnets(params, magnet_strength=1.2):
    """Draw the full N-S-N-S magnet arrangement (two magnets per pole)."""
    pole_pitch = 360 / (2 * params['p'])
    for i in range(int(2 * params['p'])):
        base_angle = i * pole_pitch
        polarity = 1 if (i % 2 == 0) else -1

        draw_magnet(base_angle, params['magnet_open'],
                    params['R_rotor_outer'], params['R_magnet'],
                    direction=polarity, magnet_strength=magnet_strength)
        draw_magnet(base_angle + params['magnet_open'] + params['magnet_gap'],
                    params['magnet_open'],
                    params['R_rotor_outer'], params['R_magnet'],
                    direction=polarity, magnet_strength=magnet_strength)


def ensure_material(name, add_material):
    """Fetch a FEMM material, creating it via ``add_material`` if missing."""
    try:
        femm.mi_getmaterial(name)
    except Exception:
        add_material()


def add_standard_materials(ndfeb_hc):
    """Register Air, M-19 Steel, and NdFeB (with the given coercivity)."""
    ensure_material("Air", lambda: femm.mi_addmaterial("Air", 1, 1))
    ensure_material("M-19 Steel",
                    lambda: femm.mi_addmaterial("M-19 Steel", 4000, 4000))
    ensure_material("NdFeB",
                    lambda: femm.mi_addmaterial("NdFeB", 1.05, 1.05, ndfeb_hc))


def add_common_block_labels(params, r_slot):
    """Block labels shared by both tools: inner air, rotor steel, stator
    steel, and the air gap between magnets."""
    # Air region inside the inner circle.
    femm.mi_addblocklabel(0, 0)
    femm.mi_selectlabel(0, 0)
    femm.mi_setblockprop("Air", 0, 1, "<None>", 0, 0, 1)
    femm.mi_clearselected()

    # Rotor steel between inner radius and rotor outer radius.
    midpoint_radius = (params['R_inner'] + params['R_rotor_outer']) / 2
    femm.mi_addblocklabel(midpoint_radius, 0)
    femm.mi_selectlabel(midpoint_radius, 0)
    femm.mi_setblockprop("M-19 Steel", 0, 1, "<None>", 0, 0, 1)
    femm.mi_clearselected()

    # Stator steel between the slot bottom and the outer radius.
    stator_r_mid = (r_slot + params['R_stator_extr']) / 2
    angle_between_slots = params['slot_pitch'] / 2
    x = stator_r_mid * math.cos(math.radians(angle_between_slots))
    y = stator_r_mid * math.sin(math.radians(angle_between_slots))
    femm.mi_addblocklabel(x, y)
    femm.mi_selectlabel(x, y)
    femm.mi_setblockprop("M-19 Steel", 0, 1, "<None>", 0, 0, 1)
    femm.mi_clearselected()

    # Air label in the gap between magnets.
    gap_angle = params['magnet_open'] + params['magnet_gap'] / 2
    r_mid = (params['R_rotor_outer'] + params['R_magnet']) / 2
    x = r_mid * math.cos(math.radians(gap_angle))
    y = r_mid * math.sin(math.radians(gap_angle))
    femm.mi_addblocklabel(x, y)
    femm.mi_selectlabel(x, y)
    femm.mi_setblockprop("Air", 0, 1, "<None>", 0, 0, 1)
    femm.mi_clearselected()


def apply_asymptotic_boundary(r_outer):
    """Mixed (asymptotic) boundary condition on the outer stator arcs."""
    femm.mi_addboundprop("Boundary", 0, 0, 0, 0, 0, 0, 1 / r_outer,
                         0, 0, 0, 0, 0, 0)

    for quadrant_angle in (45, 135, 225, 315):
        femm.mi_selectarcsegment(
            r_outer * math.cos(math.radians(quadrant_angle)),
            r_outer * math.sin(math.radians(quadrant_angle)))

    femm.mi_setarcsegmentprop(5, "Boundary", 0, 1)
    femm.mi_clearselected()
