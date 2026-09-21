"""Author: Fabio Casagrande Hirono.

Local optimization: evaluate the identical normalized integral with SciPy's
vectorized Fresnel special function instead of per-point numerical quadrature.
"""
import numpy as np
from scipy.special import fresnel


def fr_integrand_re(x):
    return (np.exp(1j*x)/np.sqrt(x)).real


def fr_integrand_im(x):
    return (np.exp(1j*x)/np.sqrt(x)).imag


def fr_int(zeta):
    """Integral_0^zeta exp(i*t)/sqrt(t) dt / sqrt(2*pi).

    Substitution t = pi*u**2/2 gives C(u) + i*S(u). Supports scalar,
    multidimensional and complex arguments, including the zero limit.
    """
    s, c = fresnel(np.sqrt(2*np.asarray(zeta)/np.pi))
    return c + 1j*s


def fr_int_cc(zeta):
    """Conjugate-kernel Fresnel integral, C(u) - i*S(u)."""
    s, c = fresnel(np.sqrt(2*np.asarray(zeta)/np.pi))
    return c - 1j*s
