"""Render and solve odd/even phase workspaces using the actual Qt6 controls."""

import json
import os
from pathlib import Path
import sys

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PyQt6.QtWidgets import QApplication

from main import MainWindow
from core.femm_validation import slot_ampere_turns
from tools.ui_smoke_test import load_preview_fonts


def check(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    load_preview_fonts()
    window = MainWindow()
    window.resize(1200, 760)
    window.show()
    app.processEvents()
    summary = []
    for phases, slots in ((1,2),(1,12),(2,8),(3,12),(4,16),(5,20),(6,24),(9,36),(13,26),(26,52)):
        window.phases_spin.setValue(phases)
        window.slots_spin.setValue(slots)
        window.poles_spin.setValue(2)
        app.processEvents()
        if window.connection_tab.matrix is None:
            raise RuntimeError(window.feasibility_label.text())
        window.navigate_to_stage(0)
        app.processEvents()
        window.grab().save(str(output/f'{phases:02d}-phases-winding.png'))
        window.navigate_to_stage(1)
        app.processEvents()
        window.grab().save(str(output/f'{phases:02d}-phases-mmf.png'))
        window.navigate_to_stage(3)
        window.mesh_preset.setCurrentIndex(0)
        window.generate_mesh_btn.click()
        window.navigate_to_stage(4)
        window.flux_calculate_btn.click()
        app.processEvents()
        result = window.flux_density_page_ui.flux_results
        if not result or result['solver_info']['relative_residual'] > 1e-5:
            raise RuntimeError(window.flux_status_label.text())
        engine = window.connection_tab.mmf_calculator
        ni = slot_ampere_turns(engine)
        tooth = np.asarray(engine.get_tooth_mmf_data()['Resultant']['tooth_mmf'])
        np.testing.assert_allclose(np.roll(tooth,-1)-tooth, ni, atol=1e-9)
        window.grab().save(str(output/f'{phases:02d}-phases-field.png'))
        summary.append({'phases':phases,'slots':slots,
                        'matrix_shape':list(engine.matrix.shape),
                        'relative_residual':result['solver_info']['relative_residual']})
    window.close()
    (output/'multiphase-check.json').write_text(json.dumps(summary,indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    print(json.dumps(check(sys.argv[1]),indent=2))
