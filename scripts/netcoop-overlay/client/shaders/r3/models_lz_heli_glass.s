-- Only the commissioned helicopter's glass uses this material.
function normal(shader, t_base, t_second, t_detail)
    shader:begin("model_env_lq", "lz_heli_glass")
        :fog(true)
        :zb(true, false)
        :blend(true, blend.srcalpha, blend.invsrcalpha)
        :aref(true, 0)
        :sorting(3, true)
    shader:dx10texture("s_base", t_base)
    shader:dx10texture("s_env", "sky\\sky_5_cube")
    shader:dx10sampler("smp_base")
    shader:dx10sampler("smp_rtlinear")
end
