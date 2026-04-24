import numpy as np


def standardize(img):
    diff = img.max() - img.min()
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


if __name__ == "__main__":
    # print(fdspi(
    #     np.array([[1,2],[3,4]]),
    #     np.array([[4,3],[2,1]])
    # ))
    import cv2
    from pathlib import Path
    im_dir = Path("images")/"20260424_031131_110936"
    top_im = cv2.imread(im_dir/'01_top.png', cv2.IMREAD_UNCHANGED)
    bottom_im = cv2.imread(im_dir/'02_bottom.png', cv2.IMREAD_UNCHANGED)
    vertical_res = differential_phase_contrast(top_im, bottom_im)
    cv2.imwrite(im_dir/"vertical.png", standardize(vertical_res))
    left_im = cv2.imread(im_dir/'04_left.png', cv2.IMREAD_UNCHANGED)
    right_im = cv2.imread(im_dir/'03_right.png', cv2.IMREAD_UNCHANGED)
    horizontal_res = differential_phase_contrast(right_im, left_im)
    cv2.imwrite(im_dir/"horizontal.png", standardize(horizontal_res))
    res = fdspi(vertical_res[:2000, :2000], -horizontal_res[:2000, :2000])
    cv2.imwrite(im_dir/"phase_diagram.png", standardize(res))
