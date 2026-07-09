"""Flux density and flux line visualisations
(formerly ``Meshing_flux_density_visualisation.py``).

Mesh geometry (patches, centres, trig factors) is cached so repeated
visualisations and animation frames don't rebuild it for every draw.
"""

import logging

import matplotlib.colors as colors
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PatchCollection
from matplotlib.patches import Circle, Wedge

try:
    from scipy.interpolate import griddata
    from scipy.ndimage import gaussian_filter
except Exception:  # pragma: no cover - scipy is expected but optional here
    griddata = None
    gaussian_filter = None

from utils.constants import DEFAULT_MACHINE_PARAMS

logger = logging.getLogger(__name__)

# Above this element count, per-element edges become visual noise.
MAX_ELEMENTS_WITH_EDGES = 5000
# Cap on scattered points handed to scipy.griddata.
MAX_INTERPOLATION_POINTS = 8000
GEOMETRY_CACHE_LIMIT = 4
PLOT_LIMIT_MARGIN = 1.2

STREAMPLOT_KWARGS = dict(
    density=1.1,
    linewidth=0.8,
    arrowstyle='-',
    minlength=0.1,
    broken_streamlines=False,
    integration_direction='both',
)

MATERIAL_COLORS = {
    'Rotor Core': '#777777',
    'Air Gap': '#E0E0E0',
    'Tooth': '#4a90e2',
    'Stator Core': '#4a90e2',
    'Slot': '#FFFFFF',
}


class FluxDensityVisualizer:
    """Renders heatmaps, flux-line streamplots, and combined views."""

    def __init__(self):
        self._mesh_geometry_cache = {}

    # ------------------------------------------------------------- geometry

    @staticmethod
    def _mesh_cache_key(mesh_elements):
        if not mesh_elements:
            return (id(mesh_elements), 0, None, None)

        first = mesh_elements[0]
        last = mesh_elements[-1]
        return (id(mesh_elements), len(mesh_elements),
                first.get('element_id', first.get('id', 0)),
                last.get('element_id', last.get('id', 0)))

    def _get_mesh_geometry(self, mesh_elements):
        """Cached patches, element ids, materials, centres, trig factors."""
        cache_key = self._mesh_cache_key(mesh_elements)
        if cache_key in self._mesh_geometry_cache:
            return self._mesh_geometry_cache[cache_key]

        num_elements = len(mesh_elements)
        patches = []
        element_ids = []
        materials = []
        center_x = np.zeros(num_elements, dtype=np.float64)
        center_y = np.zeros(num_elements, dtype=np.float64)
        cos_theta = np.zeros(num_elements, dtype=np.float64)
        sin_theta = np.zeros(num_elements, dtype=np.float64)

        for idx, element in enumerate(mesh_elements):
            element_ids.append(element.get('element_id', element.get('id')))
            materials.append(element.get('material', 'Unknown'))

            rin, rout = element['rin'], element['rout']
            theta_start, theta_end = element['theta_start'], element['theta_end']
            patches.append(Wedge((0, 0), rout, theta_start, theta_end,
                                 width=rout - rin))

            r_center = element.get('center_r', (rin + rout) * 0.5)
            theta_center = element.get('center_theta',
                                       (theta_start + theta_end) * 0.5)
            theta_rad = np.radians(theta_center)

            cos_theta[idx] = np.cos(theta_rad)
            sin_theta[idx] = np.sin(theta_rad)
            center_x[idx] = r_center * cos_theta[idx]
            center_y[idx] = r_center * sin_theta[idx]

        geometry = {
            'patches': patches,
            'element_ids': element_ids,
            'materials': materials,
            'center_x': center_x,
            'center_y': center_y,
            'cos_theta': cos_theta,
            'sin_theta': sin_theta,
        }

        if len(self._mesh_geometry_cache) >= GEOMETRY_CACHE_LIMIT:
            self._mesh_geometry_cache.clear()
        self._mesh_geometry_cache[cache_key] = geometry
        return geometry

    # ---------------------------------------------------------- data access

    @staticmethod
    def _lookup_element_data(mapping, eid):
        """Resilient per-element lookup (int and str keys both occur after
        JSON round-trips)."""
        data = mapping.get(eid)
        if data is None:
            data = mapping.get(str(eid))
        if data is None and isinstance(eid, str):
            try:
                data = mapping.get(int(eid))
            except ValueError:
                data = None
        return data

    def _extract_flux_arrays(self, flux_densities, geometry):
        """B magnitude and Cartesian B components aligned to mesh order."""
        element_ids = geometry['element_ids']
        cos_theta = geometry['cos_theta']
        sin_theta = geometry['sin_theta']

        size = len(element_ids)
        b_values = np.zeros(size, dtype=np.float64)
        bx_values = np.zeros(size, dtype=np.float64)
        by_values = np.zeros(size, dtype=np.float64)

        for idx, eid in enumerate(element_ids):
            density_data = self._lookup_element_data(flux_densities, eid)
            if not density_data:
                continue

            br = float(density_data.get('Br', 0.0))
            btheta = float(density_data.get('Btheta', 0.0))
            b_values[idx] = float(density_data.get('B_magnitude', 0.0))

            bx_values[idx] = br * cos_theta[idx] - btheta * sin_theta[idx]
            by_values[idx] = br * sin_theta[idx] + btheta * cos_theta[idx]

        return b_values, bx_values, by_values

    def _extract_b_magnitude_array(self, flux_densities, geometry):
        """B magnitude per element only (skips the Bx/By trig the heatmap
        discards). Used on the hot animation path."""
        element_ids = geometry['element_ids']
        b_values = np.zeros(len(element_ids), dtype=np.float64)
        for idx, eid in enumerate(element_ids):
            density_data = self._lookup_element_data(flux_densities, eid)
            if density_data:
                b_values[idx] = float(density_data.get('B_magnitude', 0.0))
        return b_values

    def _extract_branch_flux_vectors(self, branch_fluxes, geometry):
        """Cartesian flux vectors from up/down/left/right branch fluxes."""
        element_ids = geometry['element_ids']
        cos_theta = geometry['cos_theta']
        sin_theta = geometry['sin_theta']

        size = len(element_ids)
        fx_values = np.zeros(size, dtype=np.float64)
        fy_values = np.zeros(size, dtype=np.float64)

        for idx, eid in enumerate(element_ids):
            flux_data = self._lookup_element_data(branch_fluxes, eid)
            if not flux_data:
                continue

            # Radial is outward (+r), tangential is anti-clockwise (+theta).
            flux_radial = 0.5 * (float(flux_data.get('up', 0.0))
                                 - float(flux_data.get('down', 0.0)))
            flux_tangential = 0.5 * (float(flux_data.get('right', 0.0))
                                     - float(flux_data.get('left', 0.0)))

            fx_values[idx] = (flux_radial * cos_theta[idx]
                              - flux_tangential * sin_theta[idx])
            fy_values[idx] = (flux_radial * sin_theta[idx]
                              + flux_tangential * cos_theta[idx])

        return fx_values, fy_values

    # ------------------------------------------------------ grid interpolation

    def _vectors_to_grid(self, geometry, bx_values, by_values, limit,
                         grid_resolution):
        """Interpolate scattered element vectors onto a regular grid.

        Uses scipy.griddata when available (with gaussian smoothing),
        otherwise falls back to fast bin-averaging. Returns
        (x_grid, y_grid, u_grid, v_grid) or None when no usable data exists.
        """
        magnitudes = np.sqrt(bx_values ** 2 + by_values ** 2)
        x_grid = np.linspace(-limit, limit, grid_resolution)
        y_grid = np.linspace(-limit, limit, grid_resolution)

        if griddata is None:
            grids = self._bin_vectors_to_grid(
                geometry, bx_values, by_values, magnitudes, limit, grid_resolution)
            if grids is None:
                return None
            u_grid, v_grid = grids
            return x_grid, y_grid, u_grid, v_grid

        active = magnitudes > 0
        x_points = geometry['center_x'][active]
        y_points = geometry['center_y'][active]
        bx_points = bx_values[active]
        by_points = by_values[active]

        if len(x_points) < 5:
            return None

        if len(x_points) > MAX_INTERPOLATION_POINTS:
            stride = int(np.ceil(len(x_points) / MAX_INTERPOLATION_POINTS))
            x_points = x_points[::stride]
            y_points = y_points[::stride]
            bx_points = bx_points[::stride]
            by_points = by_points[::stride]

        x_mesh, y_mesh = np.meshgrid(x_grid, y_grid)
        points = np.column_stack((x_points, y_points))

        u_grid = griddata(points, bx_points, (x_mesh, y_mesh), method='linear')
        v_grid = griddata(points, by_points, (x_mesh, y_mesh), method='linear')

        nan_mask = np.isnan(u_grid) | np.isnan(v_grid)
        if np.any(nan_mask):
            u_nearest = griddata(points, bx_points, (x_mesh, y_mesh),
                                 method='nearest')
            v_nearest = griddata(points, by_points, (x_mesh, y_mesh),
                                 method='nearest')
            u_grid[nan_mask] = u_nearest[nan_mask]
            v_grid[nan_mask] = v_nearest[nan_mask]

        if gaussian_filter is not None:
            u_grid = gaussian_filter(u_grid, sigma=1.2)
            v_grid = gaussian_filter(v_grid, sigma=1.2)

        return x_grid, y_grid, u_grid, v_grid

    @staticmethod
    def _bin_vectors_to_grid(geometry, bx_values, by_values, magnitudes,
                             limit, grid_resolution):
        """Average element vectors into grid cells (no-scipy fallback)."""
        scale = (grid_resolution - 1) / (2.0 * limit)
        ix = ((geometry['center_x'] + limit) * scale).astype(np.int32)
        iy = ((geometry['center_y'] + limit) * scale).astype(np.int32)

        valid = ((ix >= 0) & (ix < grid_resolution)
                 & (iy >= 0) & (iy < grid_resolution)
                 & (magnitudes > 0))

        u_sum = np.zeros((grid_resolution, grid_resolution), dtype=np.float64)
        v_sum = np.zeros((grid_resolution, grid_resolution), dtype=np.float64)
        count = np.zeros((grid_resolution, grid_resolution), dtype=np.float64)

        np.add.at(u_sum, (iy[valid], ix[valid]), bx_values[valid])
        np.add.at(v_sum, (iy[valid], ix[valid]), by_values[valid])
        np.add.at(count, (iy[valid], ix[valid]), 1.0)

        populated = count > 0
        if not np.any(populated):
            return None

        u_grid = np.zeros_like(u_sum)
        v_grid = np.zeros_like(v_sum)
        u_grid[populated] = u_sum[populated] / count[populated]
        v_grid[populated] = v_sum[populated] / count[populated]
        return u_grid, v_grid

    @staticmethod
    def _machine_mask(x_grid, y_grid, machine_params):
        """Mask of grid points outside the machine annulus."""
        stator_outer_radius = machine_params.get(
            'stator_outer_radius', DEFAULT_MACHINE_PARAMS['stator_outer_radius'])
        shaft_radius = machine_params.get(
            'shaft_radius', DEFAULT_MACHINE_PARAMS['shaft_radius'])

        x_mesh, y_mesh = np.meshgrid(x_grid, y_grid)
        radial_distance = np.sqrt(x_mesh ** 2 + y_mesh ** 2)
        return (radial_distance > stator_outer_radius) | (radial_distance < shaft_radius)

    # -------------------------------------------------------------- styling

    @staticmethod
    def _apply_common_axis_style(ax, machine_params, title):
        stator_outer_radius = machine_params.get(
            'stator_outer_radius', DEFAULT_MACHINE_PARAMS['stator_outer_radius'])
        limit = stator_outer_radius * PLOT_LIMIT_MARGIN

        ax.set_aspect('equal')
        ax.set_xlim(-limit, limit)
        ax.set_ylim(-limit, limit)
        ax.set_title(title, color='black', fontsize=14, pad=20)
        ax.set_xlabel('X (mm)', color='black')
        ax.set_ylabel('Y (mm)', color='black')
        ax.tick_params(colors='black', which='both')
        for spine in ax.spines.values():
            spine.set_color('black')

    @staticmethod
    def _clear_axis(ax, figure):
        ax.clear()
        ax.set_facecolor('white')
        figure.patch.set_facecolor('white')

    # --------------------------------------------------------------- heatmap

    def generate_flux_density_heatmap(self, ax, figure, mesh_data,
                                      flux_densities, machine_params):
        """Mesh elements coloured by |B|; falls back to material colouring
        when no flux data is present."""
        try:
            self._clear_axis(ax, figure)

            mesh_elements = mesh_data['mesh_elements']
            geometry = self._get_mesh_geometry(mesh_elements)
            b_values, _, _ = self._extract_flux_arrays(flux_densities, geometry)

            if np.max(b_values) == 0:
                return self.generate_material_based_heatmap(
                    ax, figure, geometry, machine_params)

            num_elements = len(mesh_elements)
            show_edges = num_elements <= MAX_ELEMENTS_WITH_EDGES
            patch_collection = PatchCollection(
                geometry['patches'],
                linewidths=0.1 if show_edges else 0.0,
                edgecolors='black' if show_edges else 'none')

            patch_collection.set_array(b_values)
            patch_collection.set_cmap(plt.cm.turbo)
            patch_collection.set_norm(colors.Normalize(
                vmin=np.min(b_values), vmax=np.max(b_values)))
            ax.add_collection(patch_collection)

            cbar = figure.colorbar(patch_collection, ax=ax, shrink=0.8, aspect=20)
            cbar.set_label('Flux Density |B| (T)', color='black', fontsize=12)
            cbar.ax.tick_params(colors='black')

            max_b = np.max(b_values)
            avg_b = np.mean(b_values[b_values > 0]) if np.any(b_values > 0) else 0
            self._apply_common_axis_style(
                ax, machine_params,
                f'Flux Density Heatmap\n{num_elements:,} Elements | '
                f'Max B: {max_b:.3f} T | Avg B: {avg_b:.3f} T')
            return True

        except Exception as error:
            logger.error("Error generating flux density heatmap: %s", error)
            ax.clear()
            ax.text(0, 0, f"Error generating heatmap\n{str(error)[:100]}...",
                    ha='center', va='center', fontsize=12, color='red',
                    bbox=dict(boxstyle="round,pad=0.5", facecolor="#ffcccc",
                              alpha=0.8))
            ax.set_xlim(-100, 100)
            ax.set_ylim(-100, 100)
            ax.set_aspect('equal')
            return False

    def setup_heatmap_animation(self, ax, figure, mesh_data, machine_params):
        """Prepare a persistent heatmap for fast animation playback.

        Builds the patch collection, colorbar, and axis decoration ONCE, and
        returns an ``update(flux_densities) -> bool`` callable that only swaps
        the per-element colour array each frame. This avoids rebuilding ~8.6k
        wedge paths, the datalim, and the colorbar on every Wt frame (the bulk
        of the previous per-frame render cost). Returns None if no usable
        geometry exists.
        """
        mesh_elements = mesh_data['mesh_elements']
        if not mesh_elements:
            return None

        self._clear_axis(ax, figure)
        geometry = self._get_mesh_geometry(mesh_elements)
        num_elements = len(mesh_elements)
        show_edges = num_elements <= MAX_ELEMENTS_WITH_EDGES

        collection = PatchCollection(
            geometry['patches'],
            linewidths=0.1 if show_edges else 0.0,
            edgecolors='black' if show_edges else 'none')
        collection.set_cmap(plt.cm.turbo)
        collection.set_array(np.zeros(num_elements, dtype=np.float64))
        ax.add_collection(collection)

        cbar = figure.colorbar(collection, ax=ax, shrink=0.8, aspect=20)
        cbar.set_label('Flux Density |B| (T)', color='black', fontsize=12)
        cbar.ax.tick_params(colors='black')

        self._apply_common_axis_style(ax, machine_params, '')

        def update(flux_densities):
            b_values = self._extract_b_magnitude_array(flux_densities, geometry)
            if b_values.size == 0:
                return False
            vmax = float(np.max(b_values))
            if vmax <= 0:
                return False
            collection.set_array(b_values)
            collection.set_clim(float(np.min(b_values)), vmax)
            return True

        return update

    def generate_material_based_heatmap(self, ax, figure, geometry,
                                        machine_params):
        """Fallback colouring of mesh elements by material."""
        color_list = [MATERIAL_COLORS.get(material, '#CCCCCC')
                      for material in geometry['materials']]

        patch_collection = PatchCollection(
            geometry['patches'], facecolors=color_list, edgecolors='black',
            linewidths=0.15, alpha=0.8)
        ax.add_collection(patch_collection)

        self._apply_common_axis_style(
            ax, machine_params,
            'Mesh Elements (Material Based)\nNo flux density data available')

        legend_elements = [
            mlines.Line2D([0], [0], marker='s', color='black',
                          markerfacecolor=color, markersize=10,
                          label=material, markeredgecolor='black')
            for material, color in MATERIAL_COLORS.items()
        ]
        legend = ax.legend(handles=legend_elements, loc='upper right',
                           bbox_to_anchor=(1.15, 1), facecolor='white',
                           edgecolor='black')
        legend.get_frame().set_alpha(0.9)
        for text in legend.get_texts():
            text.set_color('black')
        return True

    # ------------------------------------------------------------ flux lines

    def generate_flux_lines_visualisation(self, ax, figure, mesh_data,
                                          branch_fluxes, machine_params,
                                          grid_resolution=None):
        """Streamplot of flux lines computed from branch fluxes."""
        try:
            self._clear_axis(ax, figure)

            mesh_elements = mesh_data['mesh_elements']
            geometry = self._get_mesh_geometry(mesh_elements)
            bx_values, by_values = self._extract_branch_flux_vectors(
                branch_fluxes, geometry)

            if not np.any(np.sqrt(bx_values ** 2 + by_values ** 2) > 0):
                return False

            num_elements = len(mesh_elements)
            if grid_resolution is None:
                if num_elements > 12000:
                    grid_resolution = 120
                elif num_elements > 6000:
                    grid_resolution = 140
                else:
                    grid_resolution = 160

            stator_outer_radius = machine_params.get(
                'stator_outer_radius', DEFAULT_MACHINE_PARAMS['stator_outer_radius'])
            limit = stator_outer_radius * PLOT_LIMIT_MARGIN

            grids = self._vectors_to_grid(geometry, bx_values, by_values,
                                          limit, grid_resolution)
            if grids is None:
                return False
            x_grid, y_grid, u_grid, v_grid = grids

            mask = self._machine_mask(x_grid, y_grid, machine_params)
            mag_grid = np.sqrt(np.asarray(u_grid) ** 2 + np.asarray(v_grid) ** 2)
            if np.max(mag_grid) <= 0:
                return False

            u_masked = np.ma.array(u_grid, mask=mask)
            v_masked = np.ma.array(v_grid, mask=mask)
            mag_masked = np.ma.array(mag_grid, mask=mask)
            if mag_masked.count() == 0:
                return False

            self.draw_machine_cross_section_background(ax, machine_params)

            stream = ax.streamplot(x_grid, y_grid, u_masked, v_masked,
                                   color=mag_masked, cmap='turbo', zorder=3,
                                   **STREAMPLOT_KWARGS)

            cbar = figure.colorbar(stream.lines, ax=ax, shrink=0.8, aspect=20)
            cbar.set_label('Branch Flux |Φ| (Wb)', color='black', fontsize=12)
            cbar.ax.tick_params(colors='black')

            self._apply_common_axis_style(ax, machine_params,
                                          'Flux Lines Visualisation')
            return True

        except Exception as error:
            logger.error("Error generating flux lines visualisation: %s", error)
            return False

    def generate_flux_line_density_visualisation(self, ax, figure, mesh_data,
                                                 flux_densities, branch_fluxes,
                                                 machine_params,
                                                 grid_resolution=None):
        """|B| heatmap with black flux lines overlaid."""
        try:
            self._clear_axis(ax, figure)

            mesh_elements = mesh_data['mesh_elements']
            geometry = self._get_mesh_geometry(mesh_elements)
            b_values, _, _ = self._extract_flux_arrays(flux_densities, geometry)

            if np.max(b_values) == 0:
                return self.generate_flux_lines_visualisation(
                    ax, figure, mesh_data, branch_fluxes, machine_params,
                    grid_resolution=grid_resolution)

            num_elements = len(mesh_elements)
            show_edges = num_elements <= MAX_ELEMENTS_WITH_EDGES

            patch_collection = PatchCollection(
                geometry['patches'],
                linewidths=0.1 if show_edges else 0.0,
                edgecolors='black' if show_edges else 'none',
                alpha=0.65)
            patch_collection.set_array(b_values)
            patch_collection.set_cmap(plt.cm.turbo)
            patch_collection.set_norm(colors.Normalize(
                vmin=np.min(b_values), vmax=np.max(b_values)))
            ax.add_collection(patch_collection)

            cbar = figure.colorbar(patch_collection, ax=ax, shrink=0.8, aspect=20)
            cbar.set_label('Flux Density |B| (T)', color='black', fontsize=12)
            cbar.ax.tick_params(colors='black')

            self._overlay_flux_lines(ax, geometry, branch_fluxes,
                                     machine_params, num_elements,
                                     grid_resolution)

            max_b = np.max(b_values)
            avg_b = np.mean(b_values[b_values > 0]) if np.any(b_values > 0) else 0
            self._apply_common_axis_style(
                ax, machine_params,
                f'Flux Line + Density\n{num_elements:,} Elements | '
                f'Max B: {max_b:.3f} T | Avg B: {avg_b:.3f} T')
            return True

        except Exception as error:
            logger.error(
                "Error generating flux line + density visualisation: %s", error)
            return False

    def _overlay_flux_lines(self, ax, geometry, branch_fluxes, machine_params,
                            num_elements, grid_resolution):
        """Black streamlines on top of an existing heatmap."""
        bx_values, by_values = self._extract_branch_flux_vectors(
            branch_fluxes, geometry)
        if not np.any(np.sqrt(bx_values ** 2 + by_values ** 2) > 0):
            return

        if grid_resolution is None:
            if num_elements > 12000:
                grid_resolution = 150
            elif num_elements > 6000:
                grid_resolution = 180
            else:
                grid_resolution = 220

        stator_outer_radius = machine_params.get(
            'stator_outer_radius', DEFAULT_MACHINE_PARAMS['stator_outer_radius'])
        limit = stator_outer_radius * PLOT_LIMIT_MARGIN

        grids = self._vectors_to_grid(geometry, bx_values, by_values,
                                      limit, grid_resolution)
        if grids is None:
            return
        x_grid, y_grid, u_grid, v_grid = grids

        mask = self._machine_mask(x_grid, y_grid, machine_params)
        mag_grid = np.sqrt(np.asarray(u_grid) ** 2 + np.asarray(v_grid) ** 2)
        if np.max(mag_grid) <= 0 or np.all(mask):
            return

        ax.streamplot(x_grid, y_grid,
                      np.ma.array(u_grid, mask=mask),
                      np.ma.array(v_grid, mask=mask),
                      color='black', zorder=4, **STREAMPLOT_KWARGS)

    # ------------------------------------------------------------ background

    def draw_machine_cross_section_background(self, ax, machine_params):
        """Faded machine geometry (slots/teeth/stator/rotor) behind flux
        lines."""
        defaults = DEFAULT_MACHINE_PARAMS
        try:
            stator_outer_radius = float(machine_params.get(
                'stator_outer_radius',
                machine_params.get('stator_rout', defaults['stator_outer_radius'])))
            stator_inner_radius = float(machine_params.get(
                'stator_inner_radius',
                machine_params.get('stator_rin', defaults['stator_inner_radius'])))
            num_slots = int(round(float(machine_params.get(
                'num_slots', defaults['num_slots']))))
            slot_angle = float(machine_params.get('slot_angle',
                                                  defaults['slot_angle']))
            slot_height = float(machine_params.get('slot_height',
                                                   defaults['slot_height']))
            air_gap = float(machine_params.get(
                'air_gap', machine_params.get('air_gap_thickness',
                                              defaults['air_gap'])))
            shaft_radius = float(machine_params.get('shaft_radius',
                                                    defaults['shaft_radius']))

            num_slots = max(3, num_slots)
            slot_angle = max(0.0, slot_angle)
            slot_pitch = 360.0 / num_slots
            tooth_angle = max(0.0, slot_pitch - slot_angle)

            tooth_tip_radius = min(stator_inner_radius + max(0.0, slot_height),
                                   stator_outer_radius * 0.995)
            rotor_outer_radius = max(shaft_radius + 0.2,
                                     stator_inner_radius - max(0.0, air_gap))

            ax.add_patch(Wedge(
                (0, 0), stator_outer_radius, 0, 360,
                width=max(0.1, stator_outer_radius - tooth_tip_radius),
                facecolor="#4a90e2", edgecolor="#2b4f77", alpha=0.25,
                linewidth=0.8, zorder=0))

            for i in range(num_slots):
                tooth_start = i * slot_pitch
                if tooth_angle > 0:
                    ax.add_patch(Wedge(
                        (0, 0), tooth_tip_radius, tooth_start,
                        tooth_start + tooth_angle,
                        width=max(0.1, tooth_tip_radius - stator_inner_radius),
                        facecolor="#4a90e2", edgecolor="#2b4f77", alpha=0.28,
                        linewidth=0.6, zorder=0.2))

                if slot_angle > 0:
                    slot_start = tooth_start + tooth_angle
                    ax.add_patch(Wedge(
                        (0, 0), tooth_tip_radius, slot_start,
                        slot_start + slot_angle,
                        width=max(0.1, tooth_tip_radius - stator_inner_radius),
                        facecolor="white", edgecolor="black", alpha=0.85,
                        linewidth=0.45, zorder=0.25))

            if stator_inner_radius > rotor_outer_radius:
                ax.add_patch(Wedge(
                    (0, 0), stator_inner_radius, 0, 360,
                    width=max(0.1, stator_inner_radius - rotor_outer_radius),
                    facecolor="#DDDDDD", edgecolor="#888888", alpha=0.45,
                    linewidth=0.6, zorder=0.1))

            ax.add_patch(Wedge(
                (0, 0), rotor_outer_radius, 0, 360,
                width=max(0.1, rotor_outer_radius - shaft_radius),
                facecolor="#666666", edgecolor="#3A3A3A", alpha=0.30,
                linewidth=0.8, zorder=0.15))

            ax.add_patch(Circle(
                (0, 0), shaft_radius, facecolor="white", edgecolor="#444444",
                alpha=1.0, linewidth=0.8, zorder=0.2))

        except Exception:
            # Stay resilient when machine parameters are partial.
            self.draw_machine_outline(ax, machine_params)

    @staticmethod
    def draw_machine_outline(ax, machine_params):
        """Dashed reference circles at the main machine radii."""
        defaults = DEFAULT_MACHINE_PARAMS
        stator_outer_radius = machine_params.get(
            'stator_outer_radius', defaults['stator_outer_radius'])
        stator_inner_radius = machine_params.get(
            'stator_inner_radius', defaults['stator_inner_radius'])
        air_gap = machine_params.get('air_gap', defaults['air_gap'])
        shaft_radius = machine_params.get('shaft_radius', defaults['shaft_radius'])

        rotor_outer_radius = stator_inner_radius - air_gap

        for radius in (shaft_radius, rotor_outer_radius,
                       stator_inner_radius, stator_outer_radius):
            ax.add_patch(Circle((0, 0), radius, fill=False, color='black',
                                linewidth=1.0, alpha=0.7, linestyle='--'))


_VISUALIZER = FluxDensityVisualizer()


def generate_flux_density_heatmap(ax, figure, mesh_data, flux_densities,
                                  machine_params):
    """Module-level convenience wrapper around the shared visualizer."""
    return _VISUALIZER.generate_flux_density_heatmap(
        ax, figure, mesh_data, flux_densities, machine_params)


def setup_heatmap_animation(ax, figure, mesh_data, machine_params):
    """Module-level wrapper: persistent heatmap updater for animation frames."""
    return _VISUALIZER.setup_heatmap_animation(
        ax, figure, mesh_data, machine_params)


def generate_flux_lines_visualisation(ax, figure, mesh_data, branch_fluxes,
                                      machine_params, grid_resolution=None):
    """Module-level convenience wrapper around the shared visualizer."""
    return _VISUALIZER.generate_flux_lines_visualisation(
        ax, figure, mesh_data, branch_fluxes, machine_params, grid_resolution)


def generate_flux_line_density_visualisation(ax, figure, mesh_data,
                                             flux_densities, branch_fluxes,
                                             machine_params,
                                             grid_resolution=None):
    """Module-level convenience wrapper around the shared visualizer."""
    return _VISUALIZER.generate_flux_line_density_visualisation(
        ax, figure, mesh_data, flux_densities, branch_fluxes, machine_params,
        grid_resolution)
