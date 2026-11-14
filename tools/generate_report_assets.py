"""Reproduce the three winding studies and two French scientific videos.

Run from the repository root with its Python environment. Images and videos are
scientific exports of the actual solver, rather than a geometrically rotated
snapshot. The fixed-permeability model admits two signed field bases exactly.
"""

import argparse
import csv
import json
import math
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter
from matplotlib.colors import Normalize
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.connection_matrix import build_winding_connection_matrix
from core.femm_validation import airgap_samples, slot_ampere_turns
from core.field_animation import FieldAnimationModel
from core.flux_contours import reconstruct_flux_potential
from core.flux_solver import FluxCalculator
from core.meshing_engine import MeshingEngine
from core.mmf_engine import MMFCalculationEngine
from core.reluctance_calculator import ReluctanceCalculator
from core.teeth_slot_mmf import TeethSlotMMFCalculator
from core.winding_analysis import calculate_winding_factors
from utils.constants import (DEFAULT_MACHINE_PARAMS, DEFAULT_RELATIVE_PERMEABILITIES,
                             DEFAULT_AXIAL_LENGTH_MM, MESH_PRESETS, MU0)
from utils.phases import phase_color, phase_names, phase_offsets_deg

CASES = (
    dict(slug='three-phase-default', title='Bobinage triphasé de référence', phases=3,
         slots=36, poles=4, span=9, video=True),
    dict(slug='two-phase', title='Bobinage diphasé', phases=2, slots=24,
         poles=4, span=6, video=False),
    dict(slug='five-phase-45s-8p-span5', title='Bobinage à cinq phases : pas de 5 encoches',
         phases=5, slots=45, poles=8, span=5, video=True),
)
PEAK_CURRENT, TURNS, STATIC_ANGLE = 2.8, 204, 90.0
ASSETS = ROOT / 'docs/multiphase-report/assets'
DATA = ROOT / 'docs/multiphase-report/data'
TMP = ROOT / '../../tmp/winding-report-fr'
UNIFORM_ANGLES = np.arange(16384) * 360.0 / 16384


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def config_line(case):
    return (f"{case['phases']} phases | {case['slots']} encoches | {case['poles']} pôles | "
            f"pas : {case['span']} encoches | double couche")


def paper_style():
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10.5,
        'axes.titlesize':12, 'axes.labelsize':10.5, 'axes.spines.top':False,
        'axes.spines.right':False, 'figure.facecolor':'white',
        'savefig.facecolor':'white', 'axes.grid':True, 'grid.alpha':0.20,
        'pdf.fonttype':42, 'svg.fonttype':'none'})


def spectrum(values):
    return np.fft.rfft(np.asarray(values)) * (2 / len(values))


def uniform_mmf(engine, angle):
    x, y = engine.compute_resultant_profile(angle)
    return np.interp(UNIFORM_ANGLES, x, y)


def top_harmonics(values, count=12):
    amplitudes = abs(spectrum(values))
    orders = sorted(range(1, len(amplitudes)), key=lambda n:amplitudes[n], reverse=True)[:count]
    return [{'mechanical_order':n, 'pole_count':2*n, 'peak_amplitude':float(amplitudes[n])}
            for n in orders]


def travelling_harmonics(basis, count=12):
    c, s = [spectrum(values) for values in basis]
    negative, positive = (c-1j*s)/2, (c+1j*s)/2
    weights = abs(negative)+abs(positive)
    orders = sorted(range(1, len(weights)), key=lambda n:weights[n], reverse=True)[:count]
    return [{'mechanical_order':n, 'positive_theta_peak':float(abs(positive[n])),
             'negative_theta_peak':float(abs(negative[n]))} for n in orders]


def plot_mmf(case, engine):
    fig, ax = plt.subplots(figsize=(10.5,4.5), layout='constrained')
    for phase in phase_names(case['phases']):
        x,y = engine.get_profile_data(phase, wt_deg=STATIC_ANGLE)
        ax.plot(x,y,color=phase_color(phase),lw=1.5,label=f'Phase {phase}')
    x,y = engine.compute_resultant_profile(STATIC_ANGLE)
    ax.plot(x,y,color='#171b23',lw=2.3,label='Résultante')
    ax.set(xlim=(0,360), xlabel='Position mécanique (°)', ylabel='FMM (A·t)',
        title=f"{case['title']} - FMM instantanée à φ = 90°")
    ax.set_xticks(np.arange(0,361,45))
    ax.legend(ncol=case['phases']+1, loc='upper center',bbox_to_anchor=(.5,-.15),
              frameon=False,fontsize=9)
    fig.get_layout_engine().set(rect=(0,0,1,.91))
    fig.suptitle(config_line(case)+f'\nN = {TURNS} ; courant crête configuré : {PEAK_CURRENT} A',fontsize=10.5)
    fig.savefig(ASSETS/f"{case['slug']}-mmf.png",dpi=200)
    plt.close(fig)


def map_axes(ax, model):
    ax.set_aspect('equal')
    extent = model.outer_radius*1.025
    ax.set(xlim=(-extent,extent),ylim=(-extent,extent), xlabel='x (mm)',ylabel='y (mm)')
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)


def plot_currents(case):
    angles = np.linspace(0, 360, 721)
    offsets = phase_offsets_deg(case['phases'])
    currents = PEAK_CURRENT*np.sin(np.radians(angles[:, None]+offsets))
    fig, ax = plt.subplots(figsize=(10.5, 4.0), layout='constrained')
    for index, phase in enumerate(phase_names(case['phases'])):
        ax.plot(angles, currents[:, index], color=phase_color(phase), lw=1.8,
                label=f'{phase} : {offsets[index]:g}°')
    ax.set(xlim=(0, 360), ylim=(-3.3, 3.3), xlabel='Angle électrique φ (°)',
           ylabel='Courant configuré (A)', title='Courants sinusoïdaux des phases')
    ax.set_xticks(np.arange(0, 361, 45))
    ax.legend(ncol=case['phases'], loc='upper center', bbox_to_anchor=(.5, -.16))
    fig.suptitle(config_line(case), fontsize=11)
    fig.savefig(ASSETS/f"{case['slug']}-currents.png", dpi=200)
    plt.close(fig)
    np.savetxt(DATA/f"{case['slug']}-currents.csv", np.column_stack((angles, currents)),
               delimiter=',', comments='', header='electrical_angle_deg,'+
               ','.join(f'phase_{phase}_current_a' for phase in phase_names(case['phases'])))


def audit_phase_excitation(case, matrix, mesh, settings, reluctance):
    """Check every phase independently, beyond the two temporal basis solves."""
    count = case['phases']
    engine = MMFCalculationEngine()
    engine.set_connection_matrix(matrix, count, True)
    engine.update_slot_arc(180/case['slots'])
    engine.update_turns(TURNS)
    engine.update_current(PEAK_CURRENT)
    mmf_errors = []
    for angle in (0, 37, 90, 147):
        _, full = engine.compute_resultant_profile(angle)
        partial = sum(engine.get_profile_data(phase, wt_deg=angle)[1]
                      for phase in phase_names(count))
        error = float(np.max(np.abs(full-partial)))
        np.testing.assert_allclose(full, partial, atol=1e-9, rtol=1e-11)
        mmf_errors.append(error)
    mapper, solver = TeethSlotMMFCalculator(), FluxCalculator()

    def solve(active):
        active.update_wt_angle(37)
        source = mapper.calculate_teeth_mmf(mesh, settings, active, build_full=False)
        result = solver.calculate_flux_distribution(reluctance, source,
                                                   {'method':'auto', 'tolerance':1e-8})
        values = np.array([[result['flux_densities'][e['element_id']][key]
                            for key in ('Br','Btheta')] for e in mesh['mesh_elements']])
        return values, result['solver_info']['relative_residual']

    total, total_residual = solve(engine)
    partial_fields, phases = [], []
    for index, phase in enumerate(phase_names(count)):
        isolated = np.zeros_like(matrix)
        isolated[[index, index+count]] = matrix[[index, index+count]]
        active = MMFCalculationEngine()
        active.set_connection_matrix(isolated, count, True)
        active.update_slot_arc(180/case['slots'])
        active.update_turns(TURNS)
        active.update_current(PEAK_CURRENT)
        values, residual = solve(active)
        peak = float(np.max(np.abs(values)))
        assert peak > 1e-8, f'Absent field contribution: phase {phase}'
        partial_fields.append(values)
        phases.append({'phase':phase, 'offset_deg':float(phase_offsets_deg(count)[index]),
                       'field_max_abs_component_t':peak, 'relative_residual':residual})
    error = float(np.max(np.abs(np.sum(partial_fields, axis=0)-total)))
    np.testing.assert_allclose(np.sum(partial_fields, axis=0), total, atol=1e-9, rtol=1e-7)
    return {'phase_count':count, 'matrix_shape':list(matrix.shape),
            'phase_offsets_deg':phase_offsets_deg(count).tolist(),
            'configured_currents_at_90deg_a':(PEAK_CURRENT*np.sin(np.radians(90+phase_offsets_deg(count)))).tolist(),
            'mmf_phase_sum_angles_deg':[0,37,90,147], 'mmf_phase_sum_max_abs_errors_a_turn':mmf_errors,
            'independent_field_angle_deg':37, 'total_field_relative_residual':total_residual,
            'individual_phase_solves':phases, 'field_phase_sum_max_abs_error_t':error,
            'note':'All phase excitations are included; two temporal bases are not two electrical phases.'}


def plot_field(case, model):
    fig, axes = plt.subplots(1,2,figsize=(11.5,5.6),layout='constrained')
    extent=(-model.outer_radius,model.outer_radius,-model.outer_radius,model.outer_radius)
    paths=model.contours_at(STATIC_ANGLE,18)
    axes[0].imshow(model.material_image,origin='lower',extent=extent,interpolation='nearest')
    axes[0].plot(model.geometry_paths[:,0],model.geometry_paths[:,1],color='#868d95',lw=.35)
    axes[0].plot(paths[:,0],paths[:,1],color='#17618a',lw=.8)
    axes[0].set_title('Lignes de flux : contours de potentiel A$_z$')
    image=axes[1].imshow(model.image_at(STATIC_ANGLE),origin='lower',extent=extent,
                         cmap='viridis',vmin=0,vmax=model.color_max,interpolation='nearest')
    axes[1].plot(paths[:,0],paths[:,1],color='white',lw=.45,alpha=.82)
    axes[1].set_title("Norme de l'induction |B| et lignes de flux")
    for ax in axes: map_axes(ax,model)
    fig.colorbar(image,ax=axes[1],label='|B| (T)',shrink=.83,pad=.02)
    fig.suptitle(config_line(case)+f'\nφ = 90° ; N = {TURNS} ; courant crête configuré : {PEAK_CURRENT} A',fontsize=11)
    fig.savefig(ASSETS/f"{case['slug']}-field.png",dpi=200)
    plt.close(fig)


def plot_diagnostics(case, mmf, gap_theta, br):
    fig, axes=plt.subplots(2,2,figsize=(11.5,7.0),layout='constrained')
    axes[0,0].plot(UNIFORM_ANGLES,mmf,color='#172c45',lw=1.6)
    axes[0,0].set(xlabel='Position mécanique (°)',ylabel='FMM (A·t)',xlim=(0,360),title='FMM résultante à φ = 90°')
    axes[0,1].plot(gap_theta,br,color='#126e85',lw=1.6)
    axes[0,1].set(xlabel='Position mécanique (°)',ylabel='Induction radiale (T)',xlim=(0,360),title="Induction radiale signée près du milieu de l'entrefer")
    for ax,values,label in ((axes[1,0],mmf,'Amplitude de FMM (A·t)'),
                            (axes[1,1],br,'Amplitude de B radial (T)')):
        amp=abs(spectrum(values))
        orders=np.arange(1,min(25,len(amp)))
        colors=['#bd532a' if n==case['poles']//2 else '#2c7c91' for n in orders]
        ax.bar(orders,amp[orders],color=colors,width=.72)
        ax.set(xlabel='Ordre spatial n (2n pôles)',ylabel=label,
               title=f"Spectre spatial ; orange : ordre de travail n = {case['poles']//2}")
        ax.set_xticks(np.arange(2,25,2))
    fig.suptitle(config_line(case),fontsize=11)
    fig.savefig(ASSETS/f"{case['slug']}-diagnostics.png",dpi=180)
    plt.close(fig)


def plot_four_angles(case, model):
    fig, axes=plt.subplots(1,4,figsize=(12.0,3.7),layout='constrained')
    extent=(-model.outer_radius,model.outer_radius,-model.outer_radius,model.outer_radius)
    for ax,angle in zip(axes,(0,45,90,135)):
        image=ax.imshow(model.image_at(angle),origin='lower',extent=extent,cmap='viridis',
                         vmin=0,vmax=model.color_max,interpolation='nearest')
        paths=model.contours_at(angle,14)
        ax.plot(paths[:,0],paths[:,1],color='white',lw=.35,alpha=.85)
        ax.set_aspect('equal'); ax.set_title(f'φ = {angle}°');ax.axis('off')
    fig.colorbar(image,ax=axes,label='|B| (T)',shrink=.7,pad=.01)
    fig.suptitle(config_line(case)+'\nGéométrie fixe et même échelle de couleur à tous les instants',fontsize=10.5)
    fig.savefig(ASSETS/f"{case['slug']}-rotation.png",dpi=200)
    plt.close(fig)


def make_video(case,engine,model,gap_theta,gap_basis,*,fps,seconds):
    import imageio_ffmpeg
    matplotlib.rcParams['animation.ffmpeg_path']=imageio_ffmpeg.get_ffmpeg_exe()
    fig=plt.figure(figsize=(16,9),dpi=100,facecolor='#11151b')
    ax=fig.add_axes([.025,.15,.535,.69],facecolor='white')
    ax_currents=fig.add_axes([.675,.69,.30,.16],facecolor='#f7f9fc')
    ax_mmf=fig.add_axes([.675,.365,.30,.17],facecolor='white')
    ax_br=fig.add_axes([.675,.12,.30,.15],facecolor='white')
    extent=(-model.outer_radius,model.outer_radius,-model.outer_radius,model.outer_radius)
    image=ax.imshow(model.image_at(0),origin='lower',extent=extent,cmap='viridis',vmin=0,vmax=model.color_max)
    paths=model.contours_at(0,18)
    contour,=ax.plot(paths[:,0],paths[:,1],color='white',lw=.65,alpha=.88)
    ax.plot(model.geometry_paths[:,0],model.geometry_paths[:,1],color='#dddddd',lw=.32,alpha=.65)
    map_axes(ax,model)
    ax.tick_params(colors='#d4d9df',labelsize=8)
    ax.xaxis.label.set_color('#d4d9df');ax.yaxis.label.set_color('#d4d9df')
    cb=fig.colorbar(image,ax=ax,label='|B| (T)',shrink=.83,pad=.02,fraction=.035)
    cb.ax.tick_params(colors='#d4d9df',labelsize=8)
    cb.ax.yaxis.label.set_color('#d4d9df')
    fig.text(.035,.948,case['title'],color='#f0f3f6',fontsize=21,weight='bold')
    fig.text(.035,.907,config_line(case),color='#b8c2cd',fontsize=12)
    angle_text=fig.text(.035,.10,'Angle électrique φ = 0,0°',color='#e2e8f0',fontsize=13)
    fig.text(.035,.049,'LAGHA Khalil Ellah | Réseau de réluctances linéaire, géométrie fixe',color='#c3cbd5',fontsize=10)
    fig.text(.675,.055,f'N = {TURNS} ; I crête = {PEAK_CURRENT} A ; I/couche = {PEAK_CURRENT/2} A',color='#c3cbd5',fontsize=9)
    fig.text(.675,.027,f'{seconds:g} s de lecture = 1 cycle électrique (lecture ralentie)',color='#c3cbd5',fontsize=9)
    phases=phase_names(case['phases'])
    offsets=phase_offsets_deg(case['phases'])
    phase_angles=np.linspace(0,360,721)
    current_points=[]
    current_values=[]
    for index,(phase,offset) in enumerate(zip(phases,offsets)):
        values=PEAK_CURRENT*np.sin(np.radians(phase_angles+offset))
        ax_currents.plot(phase_angles,values,color=phase_color(phase),lw=1.4,
                         label=f'{phase} ({offset:g}°)')
        point,=ax_currents.plot([0],[values[0]],marker='o',markersize=5.5,
                               color=phase_color(phase),mec='white',mew=.6)
        current_points.append(point)
        # Live values explicitly expose all current inputs, not field lobes.
        x=.675+(index%3)*.103
        y=.613-(index//3)*.026
        current_values.append(fig.text(x,y,'',color=phase_color(phase),fontsize=10.5,
                                       weight='bold'))
    current_cursor=ax_currents.axvline(0,color='#303946',ls='--',lw=.8)
    ax_currents.set(xlim=(0,360),ylim=(-PEAK_CURRENT*1.15,PEAK_CURRENT*1.15),
                    xlabel='Angle électrique φ (°)',ylabel='Courant (A)')
    ax_currents.set_xticks((0,90,180,270,360))
    ax_currents.set_title(f'{case["phases"]} courants de phase distincts : '+', '.join(phases),
                          color='#f0f3f6',fontsize=12,pad=11)
    ax_currents.legend(ncol=case['phases'],loc='upper center',bbox_to_anchor=(.5,1.03),
                        fontsize=8.3,framealpha=.9,columnspacing=.8,handlelength=1.4)
    ax_currents.tick_params(labelsize=8)
    ax_currents.xaxis.label.set_color('#d4d9df')
    ax_currents.yaxis.label.set_color('#d4d9df')
    ax_currents.tick_params(colors='#d4d9df')
    if case['phases']==5:
        fig.text(.035,.865,'Alimentation A–E à 72° ; bobinage à 8 pôles de travail',
                  color='#d8e2ed',fontsize=11)
    else:
        fig.text(.035,.865,'Alimentation triphasée A–C à 120° ; champ de travail à 4 pôles',
                  color='#d8e2ed',fontsize=11)
    mmf0,mmf90=[uniform_mmf(engine,a) for a in (0,90)]
    peak_mmf=float(np.max(np.hypot(mmf0,mmf90)))
    peak_br=float(np.max(np.hypot(*gap_basis)))
    line_mmf,=ax_mmf.plot(UNIFORM_ANGLES,mmf0,color='#1a344e',lw=1.4)
    line_br,=ax_br.plot(gap_theta,gap_basis[0],color='#14778b',lw=1.4)
    for graph,peak,ylabel,title in ((ax_mmf,peak_mmf,'FMM (A·t)','FMM résultante du bobinage'),
                                  (ax_br,peak_br,'B radial (T)',"Induction radiale dans l'entrefer")):
        graph.set(xlim=(0,360),ylim=(-peak*1.12,peak*1.12),xlabel='Position mécanique (°)',ylabel=ylabel)
        graph.set_xticks((0,90,180,270,360))
        graph.tick_params(axis='both',labelsize=8)
        graph.set_title(title,color='#e2e8f0',fontsize=11,pad=10)
        graph.xaxis.label.set_color('#d4d9df');graph.yaxis.label.set_color('#d4d9df')
        graph.tick_params(colors='#d4d9df')
    def render(angle):
        radians=np.radians(angle)
        image.set_data(model.image_at(angle))
        paths=model.contours_at(angle,18);contour.set_data(paths[:,0],paths[:,1])
        line_mmf.set_ydata(mmf0*np.cos(radians)+mmf90*np.sin(radians))
        line_br.set_ydata(gap_basis[0]*np.cos(radians)+gap_basis[1]*np.sin(radians))
        currents=PEAK_CURRENT*np.sin(np.radians(angle+offsets))
        for point,text,phase,current in zip(current_points,current_values,phases,currents):
            point.set_data([angle],[current])
            text.set_text(f'{phase} : {current:+.2f} A'.replace('.',','))
        current_cursor.set_xdata([angle,angle])
        angle_text.set_text(f'Angle électrique φ = {angle:.1f}°'.replace('.',','))

    path=ASSETS/f"{case['slug']}-flux.mp4"
    writer=FFMpegWriter(fps=fps,codec='libx264',bitrate=2400,
        extra_args=['-pix_fmt','yuv420p','-movflags','+faststart','-preset','medium','-crf','20'],
        metadata={'title':case['title'],'artist':'LAGHA Khalil Ellah',
                  'comment':config_line(case)+' ; tous les courants de phase sont inclus ; modèle linéaire sans calcul de rendement'})
    with writer.saving(fig,str(path),100):
        for frame in range(round(fps*seconds)):
            angle=frame*360/(fps*seconds)
            render(angle)
            writer.grab_frame(facecolor=fig.get_facecolor())
            if frame % 60 == 0: print(f"{case['slug']}: encoded frame {frame}/{round(fps*seconds)}",flush=True)
        render(90)
        fig.savefig(ASSETS/f"{case['slug']}-poster.jpg",dpi=100,facecolor=fig.get_facecolor())
    plt.close(fig)
    return {'file':path.name,'fps':fps,'seconds':seconds,'frames':round(fps*seconds),
            'width':1600,'height':900,'codec':'H.264','pixel_format':'yuv420p',
            'color_max_t':model.color_max,'size_bytes':path.stat().st_size,
            'language':'fr','visible_current_channels':list(phases),
            'current_traces_and_live_values':True}


def study(case,args):
    start=time.perf_counter()
    m,q,p,y=[case[key] for key in ('phases','slots','poles','span')]
    matrix=build_winding_connection_matrix(q,p,True,y,phase_names(m))
    engine=MMFCalculationEngine();engine.set_connection_matrix(matrix,m,True)
    engine.update_slot_arc(180/q);engine.update_turns(TURNS);engine.update_current(PEAK_CURRENT)
    engine.update_wt_angle(STATIC_ANGLE)
    params=dict(DEFAULT_MACHINE_PARAMS,num_slots=q,slot_angle=180/q)
    settings=dict(MESH_PRESETS[1])
    mesh=MeshingEngine().generate_mesh(params,settings)
    reluctance=ReluctanceCalculator().calculate_reluctances(mesh,DEFAULT_RELATIVE_PERMEABILITIES,
                                                           {'axial_length':DEFAULT_AXIAL_LENGTH_MM})
    mapper,solver=TeethSlotMMFCalculator(),FluxCalculator()
    solutions=[]
    for angle in (0,90):
        engine.update_wt_angle(angle)
        source=mapper.calculate_teeth_mmf(mesh,settings,engine,build_full=False)
        solutions.append(solver.calculate_flux_distribution(reluctance,source,
                                      {'method':'auto','tolerance':1e-8}))
    model=FieldAnimationModel.from_solutions(mesh,solutions,DEFAULT_AXIAL_LENGTH_MM,resolution=768)
    engine.update_wt_angle(37)
    source=mapper.calculate_teeth_mmf(mesh,settings,engine,build_full=False)
    check=solver.calculate_flux_distribution(reluctance,source,{'method':'auto','tolerance':1e-8})
    direct=np.array([[check['flux_densities'][e['element_id']][key] for key in ('Br','Btheta')]
                    for e in mesh['mesh_elements']])
    animation_error=float(np.max(np.abs(direct-model.field_at(37))))
    np.testing.assert_allclose(direct,model.field_at(37),atol=1e-9,rtol=1e-7)
    engine.update_wt_angle(STATIC_ANGLE)
    slot_ni=slot_ampere_turns(engine)
    tooth=np.array(engine.get_tooth_mmf_data()['Resultant']['tooth_mmf'])
    np.testing.assert_allclose(np.roll(tooth,-1)-tooth,slot_ni,atol=1e-9)
    samples=airgap_samples(mesh)
    sample_indices=np.array([e['element_id']-1 for e in samples])
    gap_theta=np.array([e['center_theta'] for e in samples])
    gap_basis=model.field_basis[:,sample_indices,0]
    br=gap_basis[1]
    mmf=uniform_mmf(engine,STATIC_ANGLE)
    plot_mmf(case,engine);plot_currents(case);plot_field(case,model);plot_diagnostics(case,mmf,gap_theta,br)
    plot_four_angles(case,model)
    with (DATA/f"{case['slug']}-matrix.csv").open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['phase_layer']+[f'slot_{s+1}' for s in range(q)])
        for row,label in zip(matrix,[f'{phase}_{layer}' for layer in ('top','bottom') for phase in phase_names(m)]):
            writer.writerow([label]+row.tolist())
    with (DATA/f"{case['slug']}-mmf.csv").open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['mechanical_angle_deg']+[f'phase_{phase}_a_turn' for phase in phase_names(m)]+['resultant_a_turn'])
        phase_profiles=[engine.get_profile_data(phase,wt_deg=STATIC_ANGLE) for phase in phase_names(m)]
        arrays=[np.interp(UNIFORM_ANGLES,x,values) for x,values in phase_profiles]
        writer.writerows(zip(UNIFORM_ANGLES,*arrays,mmf))
    np.savetxt(DATA/f"{case['slug']}-airgap.csv",np.column_stack((gap_theta,br,
        model.field_basis[1,sample_indices,1])),delimiter=',',comments='',
        header='mechanical_angle_deg,br_t,btheta_t')
    np.savez_compressed(TMP/f"{case['slug']}-basis.npz",field_basis=model.field_basis,
        potential_basis=model.potential_basis,contour_x=model.contour_x,contour_y=model.contour_y)
    potentials=[reconstruct_flux_potential(mesh,s['branch_fluxes'],DEFAULT_AXIAL_LENGTH_MM) for s in solutions]
    mu=np.array([DEFAULT_RELATIVE_PERMEABILITIES['ur_air'] if e['material'] in ('Slot','Air Gap')
                 else DEFAULT_RELATIVE_PERMEABILITIES['ur_stator'] for e in mesh['mesh_elements']])*MU0
    volume=np.array([.5*((e['rout']*.001)**2-(e['rin']*.001)**2)*np.radians(e['theta_end']-e['theta_start'])*.110
                     for e in mesh['mesh_elements']])
    cycle_energy=[];cycle_gap_peak=[];cycle_field_peak=[]
    for angle in np.arange(0,360,1):
        field=model.field_at(angle);b2=np.sum(field*field,axis=1)
        cycle_energy.append(float(np.sum(b2/(2*mu)*volume)))
        cycle_gap_peak.append(float(np.max(np.abs(field[sample_indices,0]))))
        cycle_field_peak.append(float(np.sqrt(b2.max())))
    amps_mmf=abs(spectrum(mmf));amps_br=abs(spectrum(br));working=p//2
    factors=calculate_winding_factors(q,p,y,True,m)
    mmf_basis=np.array([uniform_mmf(engine,a) for a in (0,90)])
    result=dict(case)
    result.update({'author':'LAGHA Khalil Ellah','layers':'double','turns':TURNS,
        'peak_current_a':PEAK_CURRENT,'layer_current_peak_a':PEAK_CURRENT/2,
        'snapshot_wt_deg':STATIC_ANGLE,'phase_offsets_deg':phase_offsets_deg(m).tolist(),
        'pole_pairs':working,'gcd_slots_pole_pairs':math.gcd(q,working),
        'slots_per_pole_per_phase':q/(p*m),'electrical_slot_angle_deg':360*working/q,
        'electrical_coil_span_deg':360*working*y/q,'winding_factors':factors,
        'machine_geometry':params,'axial_length_mm':DEFAULT_AXIAL_LENGTH_MM,
        'relative_permeabilities':DEFAULT_RELATIVE_PERMEABILITIES,'mesh_settings':settings,
        'mesh_stats':mesh['mesh_stats'],'matrix_shape':list(matrix.shape),
        'top_conductors_per_phase':abs(matrix[:m]).sum(axis=1).tolist(),
        'conductors_per_phase':(abs(matrix[:m]).sum(axis=1)+abs(matrix[m:]).sum(axis=1)).tolist(),
        'solver_basis':[s['solver_info'] for s in solutions],
        'contour_relative_residual_basis':[p.relative_residual for p in potentials],
        'animation_direct_check_37deg_max_abs_t':animation_error,
        'phase_excitation_audit':audit_phase_excitation(case,matrix,mesh,settings,reluctance),
        'airgap_sample_radius_mm':samples[0]['center_r'],'airgap_sample_count':len(samples),
        'mmf_working_harmonic_peak_a_turn':float(amps_mmf[working]),
        'br_working_harmonic_peak_t':float(amps_br[working]),
        'mmf_harmonics_at_90deg':top_harmonics(mmf),
        'br_harmonics_at_90deg':top_harmonics(br),
        'mmf_travelling_harmonics':travelling_harmonics(mmf_basis),
        'br_travelling_harmonics':travelling_harmonics(gap_basis),
        'mmf_spatial_thd_relative_to_working_harmonic':float(np.sqrt(np.sum(amps_mmf[1:]**2)-amps_mmf[working]**2)/amps_mmf[working]),
        'br_spatial_thd_relative_to_working_harmonic':float(np.sqrt(np.sum(amps_br[1:]**2)-amps_br[working]**2)/amps_br[working]),
        'global_bmag_cycle_max_t':model.color_max,
        'airgap_radial_peak_cycle_min_t':min(cycle_gap_peak),'airgap_radial_peak_cycle_max_t':max(cycle_gap_peak),
        'cell_center_energy_j_min':min(cycle_energy),'cell_center_energy_j_max':max(cycle_energy),
        'cell_center_energy_j_relative_peak_to_peak':(max(cycle_energy)-min(cycle_energy))/np.mean(cycle_energy),
        'notes':['2D linear prescribed-permeability model; no saturation, rotor-motion or loss model.',
                 'Spatial THD here includes all non-working mechanical orders, including subharmonics.',
                 'Energy is a cell-centre B-squared integral diagnostic, not a loss or efficiency calculation.',
                 'Each static density figure uses its own full-cycle fixed colour scale.',
                 'Flux contours use the application per-frame equal-Az levels; the density colour scale stays fixed for the whole cycle.'],
        'generation_seconds_before_video':time.perf_counter()-start})
    if case['video'] and not args.no_video:
        result['video']=make_video(case,engine,model,gap_theta,gap_basis,fps=args.fps,seconds=args.seconds)
    result['total_generation_seconds']=time.perf_counter()-start
    dump(DATA/f"{case['slug']}-metrics.json",result)
    print(json.dumps({'case':case['slug'],'kw':factors['total'],'br_harmonics':result['br_harmonics_at_90deg'][:5],
                      'seconds':result['total_generation_seconds']},indent=2),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-video',action='store_true')
    parser.add_argument('--fps',type=int,default=30)
    parser.add_argument('--seconds',type=float,default=12.0)
    parser.add_argument('--case',choices=[c['slug'] for c in CASES])
    args=parser.parse_args()
    for folder in (ASSETS,DATA,TMP):folder.mkdir(parents=True,exist_ok=True)
    paper_style()
    all_results=[]
    for case in CASES:
        if args.case and args.case!=case['slug']:continue
        all_results.append(study(case,args))
    if not args.case:
        dump(DATA/'study-summary.json',all_results)
        from tools.export_report_windings import export_all_windings
        export_all_windings()


if __name__=='__main__':main()
