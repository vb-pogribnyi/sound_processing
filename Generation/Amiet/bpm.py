"""BPM broadband spectra, independently expressed from NASA RP-1218 (1989).

Outputs are one-sided reference-observer PSDs [Pa^2/Hz], at r=1 m and
broadside directivity D=1. They are NOT source pressures. Equations and
limitations are documented in Generation/Noise.md. No tonal mechanisms.
"""
import numpy as np


BANDWIDTH_FACTOR = 2**(1/6) - 2**(-1/6)


def displacement_thickness(chord, reynolds, alpha_deg, tripped=True):
    """BPM NACA0012 estimates (m); alpha is relative to zero lift, degrees."""
    a = abs(alpha_deg)
    lr = np.log10(reynolds)
    if tripped:
        base = (0.0601*reynolds**(-0.114) if reynolds <= 3e5
                else 10**(3.411-1.5397*lr+0.1059*lr**2)) * chord
        suction = (10**(0.0679*a) if a <= 5 else
                   0.381*10**(0.1516*a) if a <= 12.5 else
                   14.296*10**(0.0258*a)) * base
    else:
        base = chord * 10**(3.0187-1.5397*lr+0.1059*lr**2)
        suction = (10**(0.0679*a) if a <= 7.5 else
                   0.0162*10**(0.3066*a) if a <= 12.5 else
                   52.42*10**(0.0258*a)) * base
    pressure = base * 10**(-0.0432*a+0.00113*a*a)
    return pressure, suction


def _envelopes(x, curve):
    x = np.abs(np.asarray(x))
    if curve == 'A':
        arc = np.sqrt(np.maximum(67.552-886.788*x*x, 0))-8.219
        low = np.where(x <= .204, arc, np.where(x <= .244, -32.665*x+3.981,
                       -142.795*x**3+103.656*x*x-57.757*x+6.006))
        high = np.where(x <= .13, arc, np.where(x <= .321, -15.901*x+1.098,
                        -4.669*x**3+3.491*x*x-16.699*x+1.149))
    else:
        arc = np.sqrt(np.maximum(16.888-886.788*x*x, 0))-4.109
        low = np.where(x <= .13, arc, np.where(x <= .145, -83.607*x+8.138,
                       -817.81*x**3+355.21*x*x-135.024*x+10.619))
        high = np.where(x <= .1, arc, np.where(x <= .187, -31.313*x+1.854,
                        -80.541*x**3+44.174*x*x-39.381*x+2.344))
    return low, high


def _shape(ratio, reynolds, curve):
    if curve == 'A':
        x0 = (.57 if reynolds < 9.52e4 else
              -9.57e-13*(reynolds-8.57e5)**2+1.13 if reynolds < 8.57e5 else 1.13)
    else:
        x0 = (.30 if reynolds < 9.52e4 else
              -4.48e-13*(reynolds-8.57e5)**2+.56 if reynolds < 8.57e5 else .56)
    lo0, hi0 = _envelopes(x0, curve)
    fraction = (-20-lo0)/(hi0-lo0)
    lo, hi = _envelopes(np.log10(ratio), curve)
    return lo + fraction*(hi-lo)


def trailing_edge_psd(f, *, speed, chord, span, alpha_deg, delta_pressure,
                      delta_suction, sound_speed=343., viscosity=1.5e-5,
                      density=1.225):
    """BPM Eqs. 24-49, including the empirical separated-flow branch.

    Continuous PSD approximation: evaluate the third-octave band fit at f,
    then divide its mean-square pressure by the local band width. f > 0.
    delta_* are displacement thicknesses, not 99% boundary-layer thickness.
    """
    f = np.asarray(f)
    a = abs(alpha_deg)
    re = speed*chord/viscosity
    m = speed/sound_speed
    st1 = .02*m**(-.6)
    st2 = st1*(1 if a <= 1.333 else 10**(.0054*(a-1.333)**2)
               if a <= 12.5 else 4.72)
    k1 = (-4.31*np.log10(re)+156.3 if re < 2.47e5 else
          -9*np.log10(re)+181.6 if re <= 8e5 else 128.5)
    re_dp = delta_pressure*speed/viscosity
    dk1 = -a*(5.29-1.43*np.log10(re_dp)) if re_dp <= 5000 else 0.
    gamma, beta = 27.094*m+3.31, 72.650*m+10.74
    gamma0, beta0 = 23.430*m+4.651, -34.190*m-13.820
    if a <= gamma0-gamma:
        dk2 = -1000.
    elif a <= gamma0+gamma:
        dk2 = np.sqrt(max(0., beta**2-(beta/gamma)**2*(a-gamma0)**2))+beta0
    else:
        dk2 = -12.
    stp, sts = f*delta_pressure/speed, f*delta_suction/speed
    if a >= gamma0 or a > 12.5:
        # NASA Eqs. 28-30: suppress attached pressure/suction contributions.
        band_power = delta_suction*m**5*span * 10**(
            (_shape(sts/st2, 3*re, 'A')+k1+dk2)/10)
    else:
        band_power = m**5*span * (
            delta_pressure*10**((_shape(stp/st1, re, 'A')+k1-3+dk1)/10)
            + delta_suction*10**((_shape(sts/((st1+st2)/2), re, 'A')+k1-3)/10)
            + delta_suction*10**((_shape(sts/st2, re, 'B')+k1+dk2)/10))
    return (20e-6)**2 * band_power * (density/1.225)**2 / (BANDWIDTH_FACTOR*f)


def tip_psd(f, *, speed, chord, alpha_deg, shape='rounded',
            loading_ratio=1., separation_length=None, sound_speed=343., density=1.225):
    """BPM Eqs. 61-67. Returns (reference PSD, separation length in m).

    The Mach factor is M^2 M_max^3, per NASA Eq. 61 (some secondary
    documentation transcribes this exponent incorrectly).
    """
    a = abs(alpha_deg)*loading_ratio
    if shape not in ('rounded', 'square'):
        raise ValueError('tip shape must be rounded or square')
    length = separation_length
    if length is None:
        length = chord*(.008*a if shape == 'rounded' else
                        .023+.0169*a if a <= 2 else .0378+.0095*a)
    if a == 0 or length == 0:
        return np.zeros_like(f, dtype=float), length
    mach = speed/sound_speed
    mmax = mach*(1+.036*a)
    st = np.asarray(f)*length/(mmax*sound_speed)
    spl = 10*np.log10(mach**2*mmax**3*length**2) - 30.5*(np.log10(st)+.3)**2 + 126
    psd = (20e-6)**2 * 10**(spl/10) / (BANDWIDTH_FACTOR*np.asarray(f))
    return psd*(density/1.225)**2, length
