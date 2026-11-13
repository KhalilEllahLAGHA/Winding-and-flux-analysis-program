"""Winding feasibility checks, winding factors, and the explanatory report
shown in the Winding Simulator tab."""

import math
from fractions import Fraction

from core.connection_matrix import build_winding_connection_matrix
from utils.constants import GRID_FREQUENCY_HZ, PHASE_COUNT

# Heuristic thresholds used by the report recommendations.
MIN_SLOTS_PER_POLE_PER_PHASE = 0.25
HIGH_SLOT_COUNT_THRESHOLD = 48
LOW_TORQUE_RIPPLE_SLOT_FACTOR = 6


def slots_per_pole_per_phase(slots, poles):
    """Return q = slots / (3 * poles) as an exact fraction."""
    return Fraction(slots, PHASE_COUNT * poles)


def check_winding_feasibility(slots, poles):
    """Validate a slot/pole combination for a balanced three-phase winding.

    Returns (feasible, messages, q) where messages explains each violation.
    """
    q = slots_per_pole_per_phase(slots, poles)
    messages = []

    if slots % 2 != 0:
        messages.append("- Number of slots must be even")

    if (slots * poles) % PHASE_COUNT != 0:
        messages.append("- Configuration doesn't allow balanced three-phase winding")

    if float(q) < MIN_SLOTS_PER_POLE_PER_PHASE:
        messages.append("- Slots per pole per phase too low")

    return not messages, messages, q


def calculate_winding_factors(slots, poles, coil_span, is_double_layer=True):
    """Working-harmonic factors of the actual equal-turn coil layout.

    Electrical slot angle is pi*poles/slots. The normalized signed-conductor
    phasor gives kw for integer and fractional-slot layouts. The planar
    model's zero-skew geometry gives ks=1. Unsupported layouts retain an
    explanation.
    """
    factors = {'distribution': None, 'pitch': None, 'skew': 1.0, 'total': None}
    try:
        slot_angle = math.pi * poles / slots
        if not math.isfinite(slot_angle) or slot_angle <= 0:
            raise ValueError('Slot and pole counts must be positive and finite.')
        kp = abs(math.sin(coil_span * slot_angle / 2))
        if kp < 1e-12:
            kp = 0.0
        factors['pitch'] = kp
        matrix = build_winding_connection_matrix(
            slots, poles, is_double_layer, coil_span)
    except (ValueError, TypeError, ZeroDivisionError, OverflowError) as error:
        factors['error'] = str(error)
        return factors

    phase_angles = [2 * math.pi * (poles // 2) * slot / slots
                    for slot in range(slots)]
    phasors = [complex(math.cos(angle), -math.sin(angle))
               for angle in phase_angles]
    complete = matrix[:3] + matrix[3:] if is_double_layer else matrix
    counts = abs(matrix[:3]).sum(axis=1)
    if is_double_layer:
        counts += abs(matrix[3:]).sum(axis=1)
    kw = math.fsum(abs(sum(value * phasor for value, phasor in zip(row, phasors)))
                   / count for row, count in zip(complete, counts)) / PHASE_COUNT
    if kp:
        kd = kw / kp
    else:
        # A full electrical-period double-layer span cancels all excitation,
        # but the distribution of its coil starts is still well defined.
        kd = math.fsum(abs(sum(value * phasor for value, phasor in zip(row, phasors)))
                       / abs(row).sum() for row in matrix[:3]) / PHASE_COUNT
        kw = 0.0
    factors.update(distribution=min(1.0, kd), total=min(1.0, kw))
    return factors


def predict_performance(slots, poles):
    """Rough electromagnetic performance indicators for the report."""
    speed_rpm = (GRID_FREQUENCY_HZ * 60 * 2) / poles
    is_fractional = Fraction(slots, poles).denominator > 1

    return {
        'sync_speed': speed_rpm,
        'cogging': "Low" if is_fractional else "Moderate",
        'torque_ripple': "Low" if slots > (poles * LOW_TORQUE_RIPPLE_SLOT_FACTOR) else "Moderate",
    }


def generate_winding_explanation(slots, poles, coil_span, is_double_layer, q):
    """Build the multi-section text report describing the configuration."""
    factors = calculate_winding_factors(slots, poles, coil_span, is_double_layer)
    performance = predict_performance(slots, poles)

    sections = [
        _basic_configuration_section(slots, poles, coil_span, is_double_layer),
        _technical_parameters_section(slots, poles, coil_span, q, is_double_layer),
        _winding_factors_section(factors),
        _performance_section(performance, poles, q),
        _harmonics_section(is_double_layer, poles, q),
        _construction_section(slots, poles, coil_span, is_double_layer, q),
    ]
    return "\n".join("\n".join(section) for section in sections)


def _basic_configuration_section(slots, poles, coil_span, is_double_layer):
    return [
        "1. BASIC CONFIGURATION",
        f"• Number of slots: {slots}",
        f"• Number of poles: {poles}",
        f"• Coil span: {coil_span} slots",
        f"• Winding type: {'Double layer' if is_double_layer else 'Single layer'}\n",
    ]


def _technical_parameters_section(slots, poles, coil_span, q, is_double_layer):
    lines = [
        "2. TECHNICAL PARAMETERS",
        f"• Slots per pole (S/P): {slots / poles:.2f}",
        f"• Slots per pole per phase (q): {q}",
        f"• Electrical angle between slots: {180 * poles / slots:.1f}°",
    ]
    if is_double_layer:
        lines.append(f"• Coil pitch: {coil_span / (slots / poles) * 100:.1f}% of pole pitch\n")
    return lines


def _winding_factors_section(factors):
    def display(key):
        value = factors[key]
        return f'{value:.3f}' if value is not None else 'not available for this layout'

    lines = [
        "3. WINDING FACTORS",
        f"• Distribution factor (kd): {display('distribution')}",
        f"• Pitch factor (kp): {display('pitch')}",
        f"• Skew factor (ks): {display('skew')} (unskewed planar model)",
        f"• Total winding factor (kw): {display('total')}\n",
    ]
    if factors.get('error'):
        lines.append(f"• Layout limitation: {factors['error']}\n")
    return lines


def _performance_section(performance, poles, q):
    lines = [
        "4. ELECTROMAGNETIC PERFORMANCE",
        f"• Synchronous speed: {performance['sync_speed']} RPM",
        f"• Expected cogging torque: {performance['cogging']}",
        f"• Expected torque ripple: {performance['torque_ripple']}",
    ]
    if q.denominator > 1:
        lines += [
            "• Fractional slot benefits:",
            "  - Reduced cogging torque",
            "  - Better fault tolerance",
            "  - Shorter end windings\n",
        ]
    return lines


def _harmonics_section(is_double_layer, poles, q):
    lines = ["5. HARMONIC CHARACTERISTICS"]
    if is_double_layer:
        lines += [
            "• Double layer advantages:",
            "  - Better harmonic reduction",
            "  - Lower MMF harmonics",
        ]
    else:
        lines += [
            "• Single layer characteristics:",
            "  - Stronger fundamental",
            "  - Higher harmonic content",
        ]
    if q.denominator > 1:
        lines += [
            "• Sub-harmonics present due to fractional slots",
            f"• Working harmonics: 1, {poles - 2}, {poles + 2}\n",
        ]
    return lines


def _construction_section(slots, poles, coil_span, is_double_layer, q):
    lines = ["6. PRACTICAL CONSTRUCTION CONSIDERATIONS", "Advantages:"]
    if is_double_layer:
        lines += [
            "• Better slot filling possibility",
            "• Shorter end windings",
            "• Better cooling potential",
        ]
    else:
        lines += [
            "• Simpler to manufacture",
            "• Better insulation between phases",
            "• Higher reliability",
        ]

    lines.append("\nChallenges:")
    if slots > HIGH_SLOT_COUNT_THRESHOLD:
        lines.append("• High slot count may be difficult to manufacture")
    if q.denominator > 1:
        lines.append("• More complex winding pattern")
    if is_double_layer and coil_span > slots / poles:
        lines.append("• Long end windings may increase copper loss")

    lines.append("\nRecommendations:")
    if is_double_layer:
        lines.append(f"• Optimal coil span: {int(slots / poles)} slots")
    lines.append(f"• Slot fill factor target: {0.4 if is_double_layer else 0.45}")
    lines.append(f"• Recommended slot opening: {0.25 if slots > 36 else 0.3} × tooth pitch")
    return lines
