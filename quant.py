# -*- coding: utf-8 -*-

import numpy as np, math, operator
import time

def fwa(W, bitwidth):
    max_val = 2**(bitwidth-1) - 1
    alpha = np.abs(W).max(axis=1) / max_val
    alpha_old = alpha*1.1
    while(np.linalg.norm(alpha-alpha_old)>1e-9):
        q = W / alpha[:, np.newaxis]
        q = np.round(q)
        q = np.clip(q, -max_val, max_val)
        alpha_old = alpha
        alpha = np.sum(W*q, axis=1) / np.sum(q*q, axis=1)
    return q, alpha


def split(Q, bitwidth):
    Q_sign = np.sign(Q)
    Q_abs = np.abs(Q)
    B_sav = []
    for idx in range(bitwidth-1):
        B = (Q_abs - Q_abs.astype(np.int)//2*2)
        B *= Q_sign
        B_sav.append(B)
        Q_abs = (Q_abs.astype(np.int)//2).astype(np.float32)

    # B_sum = get_int_B(B_sav[::-1])
    # assert((B_sum*4-Q).sum()==0)

    return B_sav[::-1]


# optimal fixed-point weight approximation
def ofwa(W, bitwidth, max_epoch=50):
    assert(bitwidth >= 3)
    Q, alpha = fwa(W, bitwidth)
    B_sav = split(Q, bitwidth)
    alpha *= (2**(bitwidth-2))

    ### iterative optimization
    [m, n] = W.shape
    for _ in range(max_epoch):
        print(_)
        alpha_old = np.copy(alpha)
        B_sum = get_int_B(B_sav)
        # given Ws, optimize alpha
        alpha = np.sum(W*B_sum, axis=1) / np.sum(B_sum*B_sum, axis=1)

        if np.linalg.norm(alpha_old-alpha) <= 1e-9:
            break
        # given alpha, optimize Ws
        for bit in range(bitwidth-1):
            W_res = W - get_int_B_exclusive(B_sav, bit) * alpha[:, np.newaxis]
            B = get_ot_given_a(W_res*(2**bit), alpha)
            B_sav[bit] = B

    B_sum = get_int_B(B_sav)

    return B_sav, B_sum, alpha

def ofwa_rr(X, Y, B_sav, alpha, bitwidth, max_epoch=100):

    '''
    # X: K,C,d,d
    # Y: K,M
    # B: M,N    M kernels

    objective:
    min(Y-XWA)^2
    '''
    # X: K,N   (N=C*d*d)
    X = X.reshape(X.shape[0], -1)
    K, N = X.shape

    A = np.dot(X.T, X) # N,N

    for epoch in range(max_epoch):
        # given Bi, optimize alpha
        B_sum = get_int_B(B_sav)
        XB = np.dot(X, B_sum.T) # k,m
        alpha = np.einsum("ij,ij->j", Y, XB)
        alpha = alpha / np.einsum("ij,ij->j", XB, XB)

        # given alpha, optimize Bi
        for bit in range(bitwidth-1):
            B = B_sav[bit]
            B_others = get_int_B_exclusive(B_sav, bit) * alpha[:, np.newaxis]
            Y_res = Y - np.dot(X, B_others.T)

            T = np.dot(Y_res.T, X) # M,N
            ## fix alpha, optimize B
            # parallel degree: M
            for n in range(N):
                B[:, n] = 0
                ABn = np.dot(A[n], B.T)
                lump = 2 * (ABn * (alpha/(2**bit))- T[:, n]) # M
                B[:, n] = -np.sign(lump)
                B[np.abs(lump) < (alpha/(2**bit)) * A[n,n], n] = 0

    B_sum = get_int_B(B_sav)

    return B_sum, alpha


def get_int_B(B_sav):
    B_sum = B_sav[0].copy()
    for idx in range(1, len(B_sav)):
        B_sum += B_sav[idx] / (2**idx)
    return B_sum

def get_int_B_exclusive(B_sav, bit):
    mask = [1.0]*len(B_sav)
    mask[bit] = 0
    B_sum = B_sav[0] * mask[0]
    for idx in range(1, len(B_sav)):
        B_sum += B_sav[idx] * mask[idx] / (2**idx)
    return B_sum

