-- Shared FEMM 4.2 / Lua 4.0 body. core/femm_validation.py supplies the inputs.
-- No quit(): the isolated runner owns process lifetime and error reporting.
newdocument(0)
mi_probdef(0, "millimeters", "planar", 1e-8, axial_length, 30)

function draw_circle(r)
    mi_drawarc(r, 0, -r, 0, 180, 1)
    mi_drawarc(-r, 0, r, 0, 180, 1)
end

function label_region(r, theta, material, mesh_size)
    local x = r * cos(theta)
    local y = r * sin(theta)
    mi_addblocklabel(x, y)
    mi_selectlabel(x, y)
    mi_setblockprop(material, 0, mesh_size, "<None>", 0, 0, 0)
    mi_clearselected()
end

rotor_outer = stator_inner_radius - air_gap
slot_outer = stator_inner_radius + slot_height
slot_pitch = 2 * PI / num_slots
slot_arc = slot_angle * PI / 180
slot_area = (slot_outer^2 - stator_inner_radius^2) * slot_arc / 2

mi_addmaterial("AirCustom", 1, 1)
mi_addmaterial("StatorSteel", ur_stator, ur_stator)
mi_addmaterial("RotorSteel", ur_rotor, ur_rotor)
draw_circle(stator_outer_radius)
draw_circle(slot_outer)
draw_circle(stator_inner_radius)
draw_circle(rotor_outer)
draw_circle(shaft_radius)

for k = 0, num_slots - 1 do
    -- Match the polar mesh: tooth first, then slot in each pitch.
    local th1 = (k + 1) * slot_pitch - slot_arc
    local th2 = (k + 1) * slot_pitch
    mi_drawline(stator_inner_radius*cos(th1), stator_inner_radius*sin(th1),
                slot_outer*cos(th1), slot_outer*sin(th1))
    mi_drawline(stator_inner_radius*cos(th2), stator_inner_radius*sin(th2),
                slot_outer*cos(th2), slot_outer*sin(th2))
    local name = "Coil" .. k
    -- J in MA/m^2 equals A/mm^2; signs and phase angle come from the matrix.
    mi_addmaterial(name, 1, 1, 0, slot_ni[k + 1] / slot_area)
    label_region((stator_inner_radius+slot_outer)/2, (th1+th2)/2, name, 1)
    label_region((stator_inner_radius+slot_outer)/2,
                 k*slot_pitch+(slot_pitch-slot_arc)/2, "StatorSteel", 1)
end

-- The network is bounded at the shaft and outer yoke: A=0 gives B.normal=0.
mi_addboundprop("A0", 0, 0, 0, 0, 0, 0, 0, 0, 0)
mi_selectarcsegment(0, stator_outer_radius)
mi_selectarcsegment(0, -stator_outer_radius)
mi_selectarcsegment(0, shaft_radius)
mi_selectarcsegment(0, -shaft_radius)
mi_setarcsegmentprop(1, "A0", 0, 0)
mi_clearselected()
label_region(0, 0, "<No Mesh>", 1)
label_region((shaft_radius+rotor_outer)/2, 0, "RotorSteel", 1)
label_region((rotor_outer+stator_inner_radius)/2, 0, "AirCustom", air_gap/4)
label_region((slot_outer+stator_outer_radius)/2, 0, "StatorSteel", 1)
mi_saveas(model_path)
mi_analyze(1)
mi_loadsolution()

local br_max = 0
local br_sum = 0
local br_count = 0
local br_sum_all = 0
local flux_max = 0
local flux_sum = 0
local flux_count = 0
local flux_sum_all = 0
local peak_index = 1
local sample_out = openfile(samples_path, "w")
if sample_out == nil then error("Cannot write FEMM sample values.") end
write(sample_out, "radius_mm,theta_deg,br_t,btheta_t,bmag_t,radial_flux_wb\n")
for i = 1, getn(samples) do
    local r = samples[i][1]
    local theta = samples[i][2]
    local a, bx, by = mo_getpointvalues(r*cos(theta), r*sin(theta))
    local signed_br = bx*cos(theta) + by*sin(theta)
    local btheta = -bx*sin(theta) + by*cos(theta)
    local br = abs(signed_br)
    -- Radial flux through the same sector area used for the local B sample.
    local flux = br * r * samples[i][3] * axial_length * 1e-6
    br_sum_all = br_sum_all + br
    flux_sum_all = flux_sum_all + flux
    if br > br_max then
        br_max = br
        peak_index = i
    end
    flux_max = max(flux_max, flux)
    if br > 1e-12 then br_sum = br_sum + br; br_count = br_count + 1 end
    if flux > 1e-12 then flux_sum = flux_sum + flux; flux_count = flux_count + 1 end
    write(sample_out, format("%.12e,%.12e,%.12e,%.12e,%.12e,%.12e\n",
          r, theta*180/PI, signed_br, btheta, sqrt(bx^2+by^2),
          signed_br*r*samples[i][3]*axial_length*1e-6))
end
closefile(sample_out)
local br_avg = 0
local flux_avg = 0
if br_count > 0 then br_avg = br_sum / br_count end
if flux_count > 0 then flux_avg = flux_sum / flux_count end

local peak_r = samples[peak_index][1]
local peak_theta = samples[peak_index][2]
local peak_x = peak_r * cos(peak_theta)
local peak_y = peak_r * sin(peak_theta)
local peak_a, peak_bx, peak_by = mo_getpointvalues(peak_x, peak_y)
local peak_br = peak_bx*cos(peak_theta) + peak_by*sin(peak_theta)
local peak_btheta = -peak_bx*sin(peak_theta) + peak_by*cos(peak_theta)
local peak_bmag = sqrt(peak_bx^2 + peak_by^2)

if keep_femm_open then
    -- Scale the colour map against the whole solved machine, not just the gap.
    local plot_bmax = 0
    for i = 1, mo_numelements() do
        local n1, n2, n3, x, y = mo_getelement(i)
        local a, bx, by = mo_getpointvalues(x, y)
        plot_bmax = max(plot_bmax, sqrt(bx^2 + by^2))
    end
    main_restore()
    main_maximize()
    mo_maximize()
    mo_hidemesh()
    mo_hidepoints()
    mo_hidegrid()
    mo_showdensityplot(1, 0, max(plot_bmax, 1e-9), 0, "bmag")
    mo_showcontourplot(-1)
    mo_zoomnatural()
    mo_clearcontour()
    mo_seteditmode("point")
    showpointprops()
    mo_refreshview()
    clearconsole()
    print("FEMM comparison - current winding and machine")
    print(format("%d slots; %.0f turns; %.6g A; Wt %.6g deg", num_slots,
                 turns, excitation_current_a, wt_deg))
    print(format("Air-gap max |Br|: %.6e T", br_max))
    print(format("Air-gap mean excited |Br|: %.6e T", br_avg))
    print(format("Radial sector flux max: %.6e Wb", flux_max))
    print(format("Radial sector flux mean excited: %.6e Wb", flux_avg))
    print(format("Peak |Br| sample: x %.6f mm; y %.6f mm", peak_x, peak_y))
    print(format("r %.6f mm; theta %.6f deg", peak_r, peak_theta*180/PI))
    print(format("Br %.6e T; Btheta %.6e T; |B| %.6e T", peak_br,
                 peak_btheta, peak_bmag))
    print(format("Bx %.6e T; By %.6e T; Az %.6e Wb/m", peak_bx,
                 peak_by, peak_a))
    print("Click points in the field map to inspect B, H and A.")
    print("Full comparison and metrics are saved beside the model.")
    -- Keep the field and point readout unobstructed; the console retains metrics.
    hideconsole()
    showpointprops()
end

-- Publish results only after the requested plot/readout is ready.
local out = openfile(results_path, "w")
if out == nil then error("Cannot write FEMM validation results: " .. results_path) end
write(out, format("wt_deg=%.9e\n", wt_deg))
write(out, format("turns=%.9e\n", turns))
write(out, format("excitation_current_a=%.9e\n", excitation_current_a))
write(out, format("sample_count=%d\n", getn(samples)))
write(out, format("airgap_br_max_t=%.12e\n", br_max))
write(out, format("airgap_br_avg_excited_t=%.12e\n", br_avg))
write(out, format("airgap_flux_max_wb=%.12e\n", flux_max))
write(out, format("airgap_flux_avg_excited_wb=%.12e\n", flux_avg))
write(out, format("airgap_br_mean_abs_t=%.12e\n", br_sum_all/getn(samples)))
write(out, format("airgap_flux_mean_abs_wb=%.12e\n", flux_sum_all/getn(samples)))
write(out, format("peak_sample_x_mm=%.12e\n", peak_x))
write(out, format("peak_sample_y_mm=%.12e\n", peak_y))
write(out, format("peak_sample_br_t=%.12e\n", peak_br))
write(out, format("peak_sample_btheta_t=%.12e\n", peak_btheta))
write(out, format("peak_sample_bmag_t=%.12e\n", peak_bmag))
closefile(out)
