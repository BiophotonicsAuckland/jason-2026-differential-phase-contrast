import numpy as np
import pyfftw

def standardize(img):
    diff = img.max() - img.min()
    # return ((img - img.min()) * 255 // diff).astype('uint8')
    return ((img - img.min()) * 65535 // diff).astype('uint16')


def differential_phase_contrast(illumination1, illumination2):
    illumination1 = illumination1.astype(np.int32)
    res = (illumination1 - illumination2) / (illumination1 + illumination2)
    res[res==np.nan]=0
    return res


def fdspi(phase_grad_x, phase_grad_y):
    """
    Fourier Domain Spiral Integration (FDSPI)
    Based on: https://doi.org/10.1111/j.0022-2720.2004.01293.x
    """
    N_y, N_x = phase_grad_x.shape
    g = phase_grad_x + 1j * phase_grad_y
    G = np.fft.fft2(g)

    ramp_x = (np.linspace(-N_x/2, N_x/2, N_x) - 0.5) / N_x
    ramp_y = (np.linspace(-N_y/2, N_y/2, N_y) - 0.5) / N_y
    y, x = np.meshgrid(ramp_x, ramp_y)

    t = 2 * np.pi * (x + 1j * y)
    t[t == 0] = np.finfo(float).eps

    t = np.fft.fftshift(t)

    Gt = G / t
    phase_measure = np.fft.ifft2(Gt).imag

    return phase_measure

def _get_kernel(N_x, N_y):
    ramp_x = (np.linspace(-N_x/2, N_x/2, N_x) - 0.5) / N_x
    ramp_y = (np.linspace(-N_y/2, N_y/2, N_y) - 0.5) / N_y
    y, x = np.meshgrid(ramp_x, ramp_y)

    t = 2 * np.pi * (x + 1j * y)
    t[t == 0] = np.finfo(float).eps
    t = np.fft.fftshift(t)
    return N_x*N_y/t

class FDSPIOptimized:
    """
    High-performance FDSPI with PyFFTW and caching.
    
    Usage:
        fdspi = FDSPIOptimized()
        phase = fdspi(phase_grad_x, phase_grad_y)
        
    For repeated calls with same dimensions, this avoids reallocation
    and wisdom re-computation.
    """
    
    def __init__(self, num_threads=1, simd_aligned=True):
        self.num_threads = num_threads
        self.simd_aligned = simd_aligned
        
        self._cache = {}
    
    def _get_or_create_cache(self, shape):
        if shape in self._cache:
            return self._cache[shape]
        
        N_y, N_x = shape
        
        arr = pyfftw.empty_aligned(
            (N_y, N_x), 
            dtype=np.complex128,
            n=pyfftw.simd_alignment if self.simd_aligned else 1
        )

        # Create FFT plans with best effort for speed
        fft_plan = pyfftw.FFTW(
            arr,
            arr,
            axes=(0, 1),
            direction='FFTW_FORWARD',
            flags=['FFTW_MEASURE'],
            threads=self.num_threads
        )
        
        ifft_plan = pyfftw.FFTW(
            arr,
            arr,
            axes=(0, 1),
            direction='FFTW_BACKWARD',
            flags=['FFTW_MEASURE'],
            threads=self.num_threads
        )
        
        # Pre-compute kernel
        kernel = _get_kernel(N_x, N_y)
        
        self._cache[shape] = {
            'fft_plan': fft_plan,
            'ifft_plan': ifft_plan,
            'arr': arr,
            'kernel': kernel,
            'shape': shape
        }
        
        return self._cache[shape]
        
    
    def __call__(self, phase_grad_x, phase_grad_y):
        cache = self._get_or_create_cache(phase_grad_x.shape)

        arr = cache['arr']
        
        # Combine gradients into complex array
        arr.real = phase_grad_x
        arr.imag = phase_grad_y
        
        cache['fft_plan']()
        
        np.multiply(arr, cache['kernel'], out=arr)
        
        return cache['ifft_plan']().imag.copy()
    
    def clear_cache(self):
        """Clear cached plans and arrays."""
        self._cache.clear()

if __name__ == "__main__":
    import cv2
    from pathlib import Path
    im_dir = Path("images")/"20260506_005953_180560"
    top_im = cv2.imread(im_dir/'01_top.png', cv2.IMREAD_UNCHANGED)
    bottom_im = cv2.imread(im_dir/'02_bottom.png', cv2.IMREAD_UNCHANGED)
    vertical_res = differential_phase_contrast(top_im, bottom_im)
    # cv2.imwrite(im_dir/"vertical.png", standardize(vertical_res))
    left_im = cv2.imread(im_dir/'04_left.png', cv2.IMREAD_UNCHANGED)
    right_im = cv2.imread(im_dir/'03_right.png', cv2.IMREAD_UNCHANGED)
    horizontal_res = differential_phase_contrast(right_im, left_im)
    # cv2.imwrite(im_dir/"horizontal.png", standardize(horizontal_res))
    ffdspi = FDSPIOptimized()
    # res = ffdspi(np.zeros_like(vertical_res), np.zeros_like(-horizontal_res))
    res = ffdspi(np.zeros_like(vertical_res[:2048,:2048]), np.zeros_like(-horizontal_res[:2048,:2048]))
    import time
    start_time = time.time() * 1000
    # res = fdspi(vertical_res, -horizontal_res)
    res = ffdspi(vertical_res[:2048,:2048], -horizontal_res[:2048,:2048])
    print(time.time()*1000-start_time)
    # np.save(im_dir/"phase.npy", res)
    res = standardize(res)
    start_time = time.time() * 1000
    cv2.imwrite(im_dir/"phase_diagram.tiff", res, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
    print(time.time()*1000-start_time)
    # background = np.load(im_dir/'..'/"background"/"phase.npy")
    # cv2.imwrite(im_dir/"corrected_phase_diagram.png", standardize(res - background))
