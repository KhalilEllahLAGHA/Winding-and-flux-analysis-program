"""Save two complete electrical cycles from an already prepared field."""

from pathlib import Path
import subprocess
import tempfile

import imageio_ffmpeg
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import numpy as np


VIDEO_FRAME_COUNT = 720
VIDEO_FRAME_TIME_MS = 16
VIDEO_FPS = 1000 / VIDEO_FRAME_TIME_MS
VIDEO_DURATION_SECONDS = VIDEO_FRAME_COUNT / VIDEO_FPS
VIDEO_MODES = ('B Heatmap', 'Flux Lines', 'Flux Line + Density')


def _check_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError('Video export cancelled.')


class _VideoFigure:
    """Reuse one raster, contour path and arrow path for every encoded frame."""

    def __init__(self, model, mode, contour_count, show_arrows, metadata, size):
        self.model = model
        self.mode = mode
        self.contour_count = contour_count
        self.show_arrows = show_arrows
        width, height = size
        self.figure = Figure(figsize=(width/100, height/100), dpi=100, facecolor='#181818')
        self.canvas = FigureCanvasAgg(self.figure)
        self.axes = self.figure.add_axes([0.13, 0.12, 0.66, 0.72], facecolor='white')
        self.figure.text(0.045, 0.945, 'Winding & Flux', color='#f0f0f0', fontsize=19,
                         weight='bold')
        if metadata:
            self.figure.text(0.045, 0.885, str(metadata), color='#c9c9c9', fontsize=10,
                             wrap=True)
        self.angle_text = self.figure.text(0.95, 0.945, '', color='#f0f0f0', fontsize=15,
                                           ha='right', animated=True)
        self.figure.text(0.045, 0.035, '2 loops of 360 deg | 1 deg/frame | 16 ms/frame',
                         color='#bfbfbf', fontsize=10)
        radius = model.outer_radius
        extent = (-radius, radius, -radius, radius)
        heatmap = mode != 'Flux Lines'
        self.image = self.axes.imshow(
            model.image_at(0) if heatmap else model.material_image,
            origin='lower', extent=extent, cmap='turbo' if heatmap else None,
            vmin=0 if heatmap else None, vmax=model.color_max if heatmap else None,
            interpolation='nearest', animated=heatmap, zorder=1)
        if heatmap:
            bar_axes = self.figure.add_axes([0.81, 0.19, 0.018, 0.59])
            colorbar = self.figure.colorbar(self.image, cax=bar_axes)
            colorbar.set_label('|B| (T)', color='#e0e0e0', fontsize=11)
            colorbar.ax.tick_params(colors='#d0d0d0', labelsize=9)
        self.geometry, = self.axes.plot(
            model.geometry_paths[:, 0], model.geometry_paths[:, 1],
            color='#666666', linewidth=0.45, animated=heatmap, zorder=4)
        self.contours, = self.axes.plot([], [], color='#202020', linewidth=0.7,
                                       animated=True, zorder=5)
        self.arrow_halo, = self.axes.plot([], [], color='white', linewidth=2.6,
                                         animated=True, zorder=6)
        self.arrows, = self.axes.plot([], [], color='#202020', linewidth=1.1,
                                     animated=True, zorder=7)
        self.axes.set(xlim=(-radius*1.04, radius*1.04),
                      ylim=(-radius*1.04, radius*1.04), xlabel='x (mm)', ylabel='y (mm)')
        self.axes.set_aspect('equal')
        self.axes.tick_params(labelsize=9, colors='#d0d0d0')
        self.axes.xaxis.label.set_color('#d0d0d0')
        self.axes.yaxis.label.set_color('#d0d0d0')
        self.canvas.draw()
        self.background = self.canvas.copy_from_bbox(self.figure.bbox)

    def frame(self, angle):
        # Use the same font/render lock as the application's Matplotlib canvases.
        with self.figure._render_lock:
            return self._render_frame(angle)

    def _render_frame(self, angle):
        self.canvas.restore_region(self.background)
        if self.mode != 'Flux Lines':
            self.image.set_data(self.model.image_at(angle))
            self.axes.draw_artist(self.image)
            self.axes.draw_artist(self.geometry)
        if self.mode != 'B Heatmap':
            contours, arrows = self.model.contour_frame_at(
                angle, self.contour_count, show_arrows=self.show_arrows)
            self.contours.set_data(contours[:, 0], contours[:, 1])
            self.axes.draw_artist(self.contours)
            if self.show_arrows:
                self.arrow_halo.set_data(arrows[:, 0], arrows[:, 1])
                self.arrows.set_data(arrows[:, 0], arrows[:, 1])
                self.axes.draw_artist(self.arrow_halo)
                self.axes.draw_artist(self.arrows)
        self.angle_text.set_text(f'Wt = {angle:.0f} deg')
        self.figure.draw_artist(self.angle_text)
        return np.ascontiguousarray(np.asarray(self.canvas.buffer_rgba())[:, :, :3])

    def close(self):
        self.figure.clear()


def export_animation_video(model, path, *, mode='Flux Line + Density', contour_count=12,
                           show_arrows=True, metadata='', progress=None, cancelled=None,
                           size=(1280, 720)):
    """Export 720 frames at 62.5 fps without solving or changing the live view.

    Render the 360 unique one-degree samples once, then repeat that encoded
    cycle losslessly. The final destination is replaced only after success.
    """
    if mode not in VIDEO_MODES:
        raise ValueError('Choose a supported field display mode.')
    width, height = (int(value) for value in size)
    if width < 320 or height < 240 or width % 2 or height % 2:
        raise ValueError('Video dimensions must be even and at least 320 by 240.')
    destination = Path(path).expanduser().resolve()
    if destination.suffix.lower() != '.mp4':
        raise ValueError('Save the video as an MP4 file.')
    if not destination.parent.is_dir():
        raise ValueError('The video destination folder does not exist.')

    def report(percent, message):
        _check_cancelled(cancelled)
        if progress is not None:
            progress(percent, message)

    report(0, 'Preparing video...')
    renderer = _VideoFigure(model, mode, int(np.clip(contour_count, 4, 100)),
                            bool(show_arrows), metadata, (width, height))
    try:
        with tempfile.TemporaryDirectory(prefix='.winding-video-', dir=destination.parent) as folder:
            temporary = Path(folder).resolve()
            if temporary.parent != destination.parent:
                raise RuntimeError('Unexpected temporary video folder.')
            single_cycle = temporary / 'cycle.mp4'
            completed = temporary / 'video.mp4'
            writer = imageio_ffmpeg.write_frames(
                str(single_cycle), (width, height), fps=VIDEO_FPS, codec='libx264',
                pix_fmt_in='rgb24', pix_fmt_out='yuv420p', macro_block_size=1,
                ffmpeg_log_level='error', ffmpeg_timeout=30,
                output_params=['-crf', '20', '-preset', 'fast'])
            try:
                writer.send(None)
                for angle in range(360):
                    _check_cancelled(cancelled)
                    writer.send(renderer.frame(angle))
                    if angle % 4 == 0:
                        report(1 + int((angle+1)*89/360), f'Encoding frame {angle+1}/360...')
            finally:
                writer.close()
            report(92, 'Saving two complete loops...')
            command = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error',
                       '-nostdin', '-stream_loop', '1', '-i', str(single_cycle),
                       '-map', '0:v:0', '-c:v', 'copy', '-an', '-movflags', '+faststart',
                       '-y', str(completed)]
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    creationflags=flags, timeout=60, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.decode('utf-8', 'replace').strip()
                                   or 'Could not finish the video.')
            report(99, 'Finishing video...')
            completed.replace(destination)
    finally:
        renderer.close()
    if progress is not None:
        progress(100, 'Video saved.')
    return str(destination)
