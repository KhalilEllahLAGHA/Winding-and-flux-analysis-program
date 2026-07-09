
    if openfemm ~= nil then openfemm() end
newdocument(0)
mi_probdef(0, "millimeters", "planar", 1e-8, 110.000000, 30)

        local _pi = (math ~= nil and math.pi) or pi or 3.141592653589793
        local _sin = (math ~= nil and math.sin) or sin
        local _cos = (math ~= nil and math.cos) or cos
        local _abs = (math ~= nil and math.abs) or abs

function draw_circle(r)
    mi_drawarc(r, 0, -r, 0, 180, 1)
    mi_drawarc(-r, 0, r, 0, 180, 1)
end

mi_addmaterial("AirCustom", 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
mi_addmaterial("StatorSteel", 4000.000000, 4000.000000, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
mi_addmaterial("RotorSteel", 4000.000000, 4000.000000, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
mi_addmaterial("CoilExc", 1, 1, 0, 0.151735522, 0, 0, 0, 1, 0, 0, 0, 0, 0)

draw_circle(110.640000)
draw_circle(69.150000)
draw_circle(53.850000)
draw_circle(41.250000)
draw_circle(36.250000)
draw_circle(18.650000)

local n_slots = 36
local slot_half = (2.500000) * _pi / 180
local slot_pitch = 2 * _pi / n_slots
for k = 0, n_slots - 1 do
    local center = 2 * _pi * k / n_slots
    local th1 = center - slot_half
    local th2 = center + slot_half

    local xi1 = 41.250000 * _cos(th1)
    local yi1 = 41.250000 * _sin(th1)
    local xo1 = 53.850000 * _cos(th1)
    local yo1 = 53.850000 * _sin(th1)

    local xi2 = 41.250000 * _cos(th2)
    local yi2 = 41.250000 * _sin(th2)
    local xo2 = 53.850000 * _cos(th2)
    local yo2 = 53.850000 * _sin(th2)

    mi_drawline(xi1, yi1, xo1, yo1)
    mi_drawline(xi2, yi2, xo2, yo2)

    local rc = (41.250000 + 53.850000) * 0.5
    local xc = rc * _cos(center)
    local yc = rc * _sin(center)
    mi_addblocklabel(xc, yc)
    mi_selectlabel(xc, yc)
    mi_setblockprop("CoilExc", 1, 0, "", 0, 30 + k, 0)
    mi_clearselected()

    local tooth_center = center + 0.5 * slot_pitch
    local xt = rc * _cos(tooth_center)
    local yt = rc * _sin(tooth_center)
    mi_addblocklabel(xt, yt)
    mi_selectlabel(xt, yt)
    mi_setblockprop("StatorSteel", 1, 0, "", 0, 130 + k, 0)
    mi_clearselected()
end

mi_addboundprop("A0", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
mi_selectarcsegment(110.640000, 0)
mi_selectarcsegment(-110.640000, 0)
mi_setarcsegmentprop(2, "A0", 0, 0)
mi_clearselected()

mi_addblocklabel(89.895000, 0)
mi_selectlabel(89.895000, 0)
mi_setblockprop("AirCustom", 1, 0, "", 0, 1, 0)
mi_clearselected()

mi_addblocklabel(61.500000, 0)
mi_selectlabel(61.500000, 0)
mi_setblockprop("StatorSteel", 1, 0, "", 0, 2, 0)
mi_clearselected()

mi_addblocklabel(38.750000, 0)
mi_selectlabel(38.750000, 0)
mi_setblockprop("AirCustom", 1, 0, "", 0, 4, 0)
mi_clearselected()

mi_addblocklabel(27.450000, 0)
mi_selectlabel(27.450000, 0)
mi_setblockprop("RotorSteel", 1, 0, "", 0, 5, 0)
mi_clearselected()

mi_addblocklabel(9.325000, 0)
mi_selectlabel(9.325000, 0)
mi_setblockprop("AirCustom", 1, 0, "", 0, 6, 0)
mi_clearselected()

mi_saveas("c:/Users/Lagha/Desktop/project/backup/femm_validation/machine_validation.fem")
mi_analyze(1)
mi_loadsolution()

local n_samples = 180
local br_max = 0
local br_sum_excited = 0
local br_count_excited = 0
local flux_max = 0
local flux_sum_excited = 0
local flux_count_excited = 0

for i = 0, n_samples - 1 do
    local theta = 2 * _pi * i / n_samples
    local cx = 38.750000 * _cos(theta)
    local cy = 38.750000 * _sin(theta)

    local bx, by = mo_getb(cx, cy)
    local br = bx * _cos(theta) + by * _sin(theta)
    local abs_br = _abs(br)
    if abs_br > br_max then
        br_max = abs_br
    end
    if abs_br > 1e-12 then
        br_sum_excited = br_sum_excited + abs_br
        br_count_excited = br_count_excited + 1
    end

    local x1 = 36.250000 * _cos(theta)
    local y1 = 36.250000 * _sin(theta)
    local x2 = 41.250000 * _cos(theta)
    local y2 = 41.250000 * _sin(theta)

    mo_clearcontour()
    mo_addcontour(x1, y1)
    mo_addcontour(x2, y2)
    local line_flux = mo_lineintegral(0)
    local abs_flux = _abs(line_flux)

    if abs_flux > flux_max then
        flux_max = abs_flux
    end
    if abs_flux > 1e-12 then
        flux_sum_excited = flux_sum_excited + abs_flux
        flux_count_excited = flux_count_excited + 1
    end
end

local br_avg_excited = 0
if br_count_excited > 0 then
    br_avg_excited = br_sum_excited / br_count_excited
end

local flux_avg_excited = 0
if flux_count_excited > 0 then
    flux_avg_excited = flux_sum_excited / flux_count_excited
end

local out = io.open("c:/Users/Lagha/Desktop/project/backup/femm_validation/validation_results.txt", "w")
if out then
    out:write(string.format("wt_deg=%.6f\n", 90.000000))
    out:write(string.format("airgap_br_max_t=%.9e\n", br_max))
    out:write(string.format("airgap_br_avg_excited_t=%.9e\n", br_avg_excited))
    out:write(string.format("airgap_flux_max_wb=%.9e\n", flux_max))
    out:write(string.format("airgap_flux_avg_excited_wb=%.9e\n", flux_avg_excited))
    out:write(string.format("excitation_current_a=%.9e\n", 2.800000000e+00))
    out:write(string.format("turns=%.2f\n", 204.00))
    out:write(string.format("current_density_ma_per_m2=%.9e\n", 1.517355223e-01))
    out:close()
end

if quit ~= nil then quit() end
