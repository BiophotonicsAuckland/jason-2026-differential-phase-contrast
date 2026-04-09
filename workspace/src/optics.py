import numpy as np

def fdspi(phase_grad_x, phase_grad_y):
    """
    Fourier Domain Spiral Integration (FDSPI)
    Based on: https://doi.org/10.1111/j.0022-2720.2004.01293.x
    """
    N = phase_grad_x.shape[0]
    g = phase_grad_x + 1j * phase_grad_y
    G = np.fft.fft2(g)

    ramp = (np.linspace(-N/2, N/2, N) - 0.5) / N
    x, y = np.meshgrid(ramp, ramp)

    t = 2 * np.pi * (y + 1j * x)
    t[t == 0] = np.finfo(float).eps
    
    t = np.fft.fftshift(t)

    Gt = G / t
    phase_measure = np.fft.ifft2(Gt).imag
    
    return phase_measure

if __name__ == "__main__":
    print(fdspi(
        np.array([[1,2],[3,4]]),
        np.array([[4,3],[2,1]])
    ))