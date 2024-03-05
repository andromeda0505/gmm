import numpy as np
import pandas as pd

import scipy
import torch
import torchmin


# %%
class GMMEstimator:
    def __init__(self, moment_cond, weighting_matrix="optimal", opt="scipy"):
        """Generalized Method of Moments Estimator

        Args:
            moment_cond (function): Moment condition. Returns L X n matrix of moments
            weighting_matrix (str, optional): What kind of weight matrix to use. Defaults to 'optimal'.
            opt (str, optional): Optimization method. Defaults to 'scipy', numerical via 'torch' works more easily for large problems.

        ref: Hansen (1982), Cameron and Trivedi (2005) Chapter 6
        """
        self.moment_cond = moment_cond
        self.weighting_matrix = weighting_matrix
        self.opt = opt

    def gmm_objective(self, beta):
        """
        Quadratic form to be minimized.
        """
        moments = self.moment_cond(self.z, self.y, self.x, beta)
        if self.weighting_matrix == "optimal":
            self.W = self.optimal_weighting_matrix(moments)
        else:
            if self.opt == "scipy":
                self.W = np.eye(moments.shape[1])
            elif self.opt == "torch":
                self.W = torch.eye(moments.shape[1])
        mavg = moments.mean(axis=0)
        if self.opt == "scipy":
            return mavg.T @ self.W @mavg
        elif self.opt == "torch":
            return torch.matmul(
                mavg.unsqueeze(-1).T,
                torch.matmul(self.W, mavg),
            )

    def optimal_weighting_matrix(self, moments):
        """
        Optimal Weight matrix
        """
        if self.opt == "scipy":
            return np.linalg.inv((1 / self.n) * (moments.T @ moments))
        elif self.opt == "torch":
            return torch.inverse((1 / self.n) * torch.matmul(moments.T, moments))

    def fit(self, z, y, x, verbose=False, fit_method=None):
        if (
            fit_method is None
        ):  # sensible defaults; non-limited BFGS is faster for small problems
            fit_method = "l-bfgs" if self.opt == "torch" else "L-BFGS-B"
        if self.opt == "scipy":
            self.z, self.y, self.x = z, y, x
            self.n, self.k = x.shape
            # minimize the objective function
            result = scipy.optimize.minimize(
                self.gmm_objective,
                x0=np.random.rand(self.k),
                method=fit_method,
                options={"disp": verbose},
            )
        elif self.opt == "torch":
            # minimize blackbox using pytorch
            self.z, self.y, self.x = (
                torch.tensor(z, dtype=torch.float64),
                torch.tensor(y, dtype=torch.float64),
                torch.tensor(x, dtype=torch.float64),
            )
            self.n, self.k = x.shape
            beta_init = torch.tensor(
                np.random.rand(self.k), dtype=torch.float64, requires_grad=True
            )
            result = torchmin.minimize(
                self.gmm_objective, beta_init, method=fit_method, tol=1e-5, disp=verbose
            )
            self.W = self.W.detach().numpy()
        # solution
        self.theta = result.x

        # Standard error calculation
        try:
            self.Gamma = self.jacobian_moment_cond()
            self.vθ = np.linalg.inv(self.Gamma.T @ self.W @ self.Gamma)
            self.std_errors = np.sqrt(self.n * np.diag(self.vθ))
        except:
            self.std_errors = None

    def jacobian_moment_cond(self):
        """
        Jacobian of the moment condition
        """
        if self.opt == "scipy":  # Analytic Jacobian for linear IV; else use torch
            self.jac_est = -self.z.T @ self.x
        elif self.opt == "torch":
            # forward mode automatic differentiation wrt 3rd arg (parameter vector)
            self.jac = torch.func.jacfwd(self.moment_cond, argnums=3)
            self.jac_est = (
                self.jac(self.z, self.y, self.x, self.theta)
                .sum(axis=0)
                .detach()
                .numpy()
            )
        return self.jac_est

    def summary(self):
        return pd.DataFrame({"coef": self.theta, "std err": self.std_errors})


# %% moment conditions to pass to GMM class
def iv_moment_pytorch(z, y, x, beta):
    """Linear IV moment condition in torch"""
    return z * (y - x @ beta).unsqueeze(-1)


def iv_moment_numpy(z, y, x, beta):
    """Linear IV moment condition in numpy"""
    return z * (y - x @ beta)[:, np.newaxis]


# %%
