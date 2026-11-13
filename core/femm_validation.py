"""Build a FEMM reference from the active winding, geometry and sample ring."""

import math
import csv
from pathlib import Path

import numpy as np

from core.meshing_engine import _validate_geometry
from utils.phases import matrix_layout, phase_sin_factors
from utils.paths import FEMM_VALIDATION_SCRIPT


def lua_string(value):
    """Quote a filesystem path for FEMM's Lua 4 interpreter."""
    return '"' + str(value).replace('\\', '/').replace('"', '\\"') + '"'


def airgap_samples(mesh_data):
    """One middle air-gap mesh ring, shared by both comparison metrics."""
    elements = [e for e in mesh_data['mesh_elements']
                if e['material'] == 'Air Gap']
    if not elements:
        raise ValueError('Generate a mesh containing air-gap elements first.')
    params = mesh_data['params']
    midpoint = params['stator_inner_radius'] - params['air_gap'] / 2
    radius = min((e['center_r'] for e in elements),
                 key=lambda r: (abs(r - midpoint), r))
    return sorted((e for e in elements if e['center_r'] == radius),
                  key=lambda e: e['center_theta'])


def compute_reference_metrics(flux_results, samples, axial_length):
    """Compare radial B and radial sector flux, never tangential branches."""
    br_values, flux_values = [], []
    densities = flux_results['flux_densities']
    for element in samples:
        br = abs(float(densities[element['element_id']]['Br']))
        if not math.isfinite(br):
            raise ValueError('The current model contains non-finite air-gap B.')
        area = (element['center_r'] * 1e-3 * axial_length * 1e-3
                * math.radians(element['theta_end'] - element['theta_start']))
        br_values.append(br)
        flux_values.append(br * area)

    def excited_mean(values):
        excited = [v for v in values if v > 1e-12]
        return sum(excited) / len(excited) if excited else 0.0

    return {
        'airgap_br_max_t': max(br_values),
        'airgap_br_avg_excited_t': excited_mean(br_values),
        'airgap_flux_max_wb': max(flux_values),
        'airgap_flux_avg_excited_wb': excited_mean(flux_values),
        'airgap_br_mean_abs_t': sum(br_values) / len(br_values),
        'airgap_flux_mean_abs_wb': sum(flux_values) / len(flux_values),
    }


def airgap_profile(flux_results, samples):
    """Signed point values in the same radius/angle order as the FEMM CSV."""
    densities = flux_results['flux_densities']
    return np.array([
        [e['center_r'], e['center_theta'],
         densities[e['element_id']]['Br'], densities[e['element_id']]['Btheta']]
        for e in samples], dtype=float)


def compare_airgap_profiles(local_profile, reference_path):
    """Compare signed curves so a polarity or angular error cannot hide in peaks."""
    with Path(reference_path).open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    reference = np.array([
        [float(row[key]) for key in ('radius_mm', 'theta_deg', 'br_t', 'btheta_t')]
        for row in rows], dtype=float)
    local = np.asarray(local_profile, dtype=float)
    if (local.shape != reference.shape or local.ndim != 2
            or local.shape[1] != 4 or not len(local)
            or not np.isfinite(local).all() or not np.isfinite(reference).all()):
        raise ValueError('FEMM and network field samples must be finite and aligned.')
    if not np.allclose(local[:, :2], reference[:, :2], atol=1e-8, rtol=1e-10):
        raise ValueError('FEMM and network sample radii or angles differ.')
    result = {}
    for index, name in ((2, 'Br'), (3, 'Btheta')):
        difference = local[:, index] - reference[:, index]
        norm = float(np.linalg.norm(reference[:, index]))
        result[name] = {
            'normalized_l2_percent': float(np.linalg.norm(difference) / norm * 100)
            if norm > 1e-12 else None,
            'max_absolute_error_t': float(np.max(np.abs(difference))),
        }
    return result


def slot_ampere_turns(mmf_engine):
    """Signed NI per slot; double-layer current follows the app's split."""
    matrix = np.asarray(mmf_engine.matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise ValueError('Generate a connection matrix first.')
    count, double = matrix_layout(matrix, getattr(mmf_engine, 'phase_count', None),
                                  getattr(mmf_engine, 'is_double_layer', None))
    if not np.isfinite(matrix).all():
        raise ValueError('The connection matrix contains non-finite values.')
    if double:
        matrix = (matrix[:count] + matrix[count:]) / 2
    currents = phase_sin_factors(mmf_engine.wt_angle_deg, count)
    values = (currents @ matrix * float(mmf_engine.turns)
              * float(mmf_engine.phase_current_a))
    if not np.isfinite(values).all():
        raise ValueError('Winding excitation must be finite.')
    if abs(float(values.sum())) > max(1e-9, float(np.abs(values).sum()) * 1e-9):
        raise ValueError('The winding has unbalanced net slot ampere-turns.')
    return values


def build_validation_script(mesh_data, mmf_engine, material_properties,
                            axial_length, output_dir):
    """Write a run-specific Lua script; preserve the historical FEMM model."""
    params = dict(mesh_data['params'])
    if any(not math.isfinite(float(v)) or float(v) <= 0
           for v in params.values()):
        raise ValueError('Machine dimensions must be finite and positive.')
    _validate_geometry(params)
    if params['stator_inner_radius'] + params['slot_height'] >= params['stator_outer_radius']:
        raise ValueError('Slot height must leave room for the stator yoke.')
    if int(params['num_slots']) != params['num_slots']:
        raise ValueError('The machine slot count must be an integer.')
    if not math.isfinite(axial_length) or axial_length <= 0:
        raise ValueError('Axial length must be finite and positive.')
    for key in ('ur_stator', 'ur_rotor'):
        value = float(material_properties[key])
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Material permeabilities must be finite and positive.')
    ni = slot_ampere_turns(mmf_engine)
    if len(ni) != params['num_slots']:
        raise ValueError('Winding and machine slot counts differ. Regenerate the mesh.')
    samples = airgap_samples(mesh_data)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = ['-- Generated from the current application inputs. Lua 4.0.']
    values = {
        **params, 'axial_length': axial_length,
        'ur_stator': float(material_properties['ur_stator']),
        'ur_rotor': float(material_properties['ur_rotor']),
        'wt_deg': float(mmf_engine.wt_angle_deg),
        'turns': float(mmf_engine.turns),
        'excitation_current_a': float(mmf_engine.phase_current_a),
        'phase_count': getattr(mmf_engine, 'phase_count', 3),
    }
    lines.extend(f'{key} = {float(value):.17g}' for key, value in values.items())
    lines += [
        'model_path = ' + lua_string(output_dir / 'machine_validation.fem'),
        'results_path = ' + lua_string(output_dir / 'validation_results.txt'),
        'samples_path = ' + lua_string(output_dir / 'airgap_samples.csv'),
        'slot_ni = {' + ', '.join(f'{v:.17g}' for v in ni) + '}',
        'samples = {',
    ]
    for element in samples:
        lines.append('  {' + ', '.join(f'{v:.17g}' for v in (
            element['center_r'], math.radians(element['center_theta']),
            math.radians(element['theta_end'] - element['theta_start']))) + '},')
    lines += ['}', FEMM_VALIDATION_SCRIPT.read_text(encoding='utf-8-sig')]
    script_path = output_dir / 'run_validation.lua'
    script_path.write_text('\n'.join(lines), encoding='utf-8')
    return script_path
