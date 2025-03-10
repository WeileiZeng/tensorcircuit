"""
readout error mitigation functionalities
"""
# Part of the code in this file is from mthree: https://github.com/Qiskit-Partners/mthree

from typing import Any, Callable, List, Sequence, Optional, Union
import warnings
from time import perf_counter

import psutil
import numpy as np
import scipy.linalg as la
import scipy.sparse.linalg as spla
from scipy.optimize import minimize

try:
    from mthree.matrix import _reduced_cal_matrix
    from mthree.utils import counts_to_vector, vector_to_quasiprobs
    from mthree.norms import ainv_onenorm_est_lu, ainv_onenorm_est_iter
    from mthree.matvec import M3MatVec
    from mthree.exceptions import M3Error
    from mthree.classes import QuasiCollection

    mthree_installed = True
except ImportError:
    mthree_installed = False

from .counts import count2vec, vec2count, ct, marginal_count
from ..circuit import Circuit
from ..utils import is_sequence


Tensor = Any


class ReadoutMit:
    def __init__(self, execute: Callable[..., List[ct]], iter_threshold: int = 4096):
        """
        The Class for readout error mitigation

        :param execute: execute function to run the cirucit
        :type execute: Callable[..., List[ct]]
        :param iter_threshold: iteration threshold, defaults to 4096
        :type iter_threshold: int, optional
        """

        self.cal_qubits = None  #  qubit list for calibration
        self.use_qubits = None  # qubit list for mitigation

        self.local = None
        self.single_qubit_cals = None
        self.global_cals = None

        self.iter_threshold = iter_threshold

        self.execute_fun = execute

    def ubs(self, i: int) -> int:
        """
        Help omit calibration results that not in used qubit list.

        :param i: index
        :type i: int
        :return: omitation related value
        :rtype: int
        """
        name = "{:0" + str(len(self.cal_qubits)) + "b}"  # type: ignore
        lisbs = [int(x) for x in name.format(i)]

        vomit = 0
        for k in list(filter(lambda x: x not in self.use_qubits, self.cal_qubits)):  # type: ignore
            vomit += lisbs[self.cal_qubits.index(k)]  # type: ignore
        return vomit

    def newrange(self, m: int) -> int:
        """
        Rerange the order according to used qubit list.

        :param m: index
        :type m: int
        :return: new index
        :rtype: int
        """
        sorted_index = sorted(
            range(len(self.use_qubits)), key=lambda k: self.use_qubits[k]  # type: ignore
        )
        name = "{:0" + str(len(self.use_qubits)) + "b}"  # type: ignore
        lisbs = [int(x) for x in name.format(m)]
        lisbs2 = [lisbs[i] for i in sorted_index]

        indexstr = ""
        for i in lisbs2:
            indexstr += str(i)
        return int(indexstr, 2)

    def get_matrix(self, qubits: Optional[Sequence[Any]] = None) -> Tensor:
        """
        Calculate cal_matrix according to use qubit list.

        :param qubits: used qubit list, defaults to None
        :type qubits: Sequence[Any], optional
        :return: cal_matrix
        :rtype: Tensor
        """

        if qubits is None:
            qubits = self.use_qubits

        if self.local is False:

            lbs = [marginal_count(i, qubits) for i in self.global_cal]
            calmatrix = np.zeros((2 ** len(qubits), 2 ** len(qubits)))

            m = 0
            for i in range(len(lbs)):
                vv = self.ubs(i)
                if vv == 0:
                    for s in lbs[i]:
                        calmatrix[int(s, 2)][self.newrange(m)] = (
                            lbs[i][s] / self.cal_shots
                        )
                    m += 1
            self.calmatrix = calmatrix
            return calmatrix

        # self.local = True
        calmatrix = self.single_qubit_cals[qubits[0]]  # type: ignore
        for i in range(1, len(qubits)):  # type: ignore
            calmatrix = np.kron(calmatrix, self.single_qubit_cals[qubits[i]])  # type: ignore
        self.calmatrix = calmatrix  # type: ignore
        return calmatrix

    def _form_cals(self, qubits):  # type: ignore

        qubits = np.asarray(qubits, dtype=int)
        cals = np.zeros(4 * qubits.shape[0], dtype=float)

        # Reverse index qubits for easier indexing later
        for kk, qubit in enumerate(qubits[::-1]):
            cals[4 * kk : 4 * kk + 4] = self.single_qubit_cals[qubit].ravel()  # type: ignore
        return cals

    def local_miti_readout_circ(self) -> List[Circuit]:
        """
        Generate circuits for local calibration.

        :return: circuit list
        :rtype: List[Circuit]
        """
        # TODO(@yutuer): Note on qubit mapping
        miticirc = []
        c = Circuit(max(self.cal_qubits) + 1)  # type: ignore
        miticirc.append(c)
        c = Circuit(max(self.cal_qubits) + 1)  # type: ignore
        for i in self.cal_qubits:  # type: ignore
            c.X(i)  # type: ignore
        miticirc.append(c)
        return miticirc

    def global_miti_readout_circ(self) -> List[Circuit]:
        """
         Generate circuits for global calibration.

        :return: circuit list
        :rtype: List[Circuit]
        """
        miticirc = []
        for i in range(2 ** len(self.cal_qubits)):  # type: ignore
            name = "{:0" + str(len(self.cal_qubits)) + "b}"  # type: ignore
            lisbs = [int(x) for x in name.format(i)]
            c = Circuit(max(self.cal_qubits) + 1)  # type: ignore
            for k in range(len(self.cal_qubits)):  # type: ignore
                if lisbs[k] == 1:
                    c.X(self.cal_qubits[k])  # type: ignore
            miticirc.append(c)
        return miticirc

    def cals_from_system(  # type: ignore
        self, qubits: Union[int, List[int]], shots: int = 8192, method: str = "local"
    ):
        """
        Get calibrattion information from system.

        :param qubits: calibration qubit list
        :type qubits: Sequence[Any]
        :param shots: shots used for runing the circuit, defaults to 8192
        :type shots: int, optional
        :param method: calibration method, defaults to "local", it can also be "global"
        :type method: str, optional
        """
        if not is_sequence(qubits):
            qubits = list(range(qubits))  # type: ignore
        qubits.sort()  # type: ignore
        self.cal_qubits = qubits  # type: ignore
        self.cal_shots = shots

        if method == "local":
            self.local = True  # type: ignore
            miticirc = self.local_miti_readout_circ()
            lbsall = self.execute_fun(miticirc, self.cal_shots)
            lbs = [marginal_count(i, self.cal_qubits) for i in lbsall]  # type: ignore

            self.single_qubit_cals = [None] * (max(self.cal_qubits) + 1)  # type: ignore
            for i in range(len(self.cal_qubits)):  # type: ignore
                error00 = 0
                for s in lbs[0]:
                    if s[i] == "0":
                        error00 = error00 + lbs[0][s] / self.cal_shots  # type: ignore

                error10 = 0
                for s in lbs[1]:
                    if s[i] == "0":
                        error10 = error10 + lbs[1][s] / self.cal_shots  # type: ignore

                readout_single = np.array(
                    [
                        [error00, error10],
                        [1 - error00, 1 - error10],
                    ]
                )
                self.single_qubit_cals[self.cal_qubits[i]] = readout_single  # type: ignore

        elif method == "global":
            self.local = False  # type: ignore
            miticirc = self.global_miti_readout_circ()
            lbsall = self.execute_fun(miticirc, self.cal_shots)
            self.global_cal = lbsall

        else:
            raise ValueError("Unrecognized `miti_method`: %s" % method)

    def mitigate_probability(
        self, probability_noise: Tensor, method: str = "inverse"
    ) -> Tensor:
        """
        Get the mitigated probability.

        :param probability_noise: probability of raw count
        :type probability_noise: Tensor
        :param method: mitigation methods, defaults to "inverse", it can also be "square"
        :type method: str, optional
        :return: mitigated probability
        :rtype: Tensor
        """
        calmatrix = self.get_matrix()
        if method == "inverse":
            X = np.linalg.inv(calmatrix)
            Y = probability_noise
            probability_cali = X @ Y
        else:  # method="square"

            def fun(x: Any) -> Any:
                return sum((probability_noise - calmatrix @ x) ** 2)

            x0 = np.random.rand(len(probability_noise))
            cons = {"type": "eq", "fun": lambda x: 1 - sum(x)}
            bnds = tuple((0, 1) for x in x0)
            res = minimize(
                fun, x0, method="SLSQP", constraints=cons, bounds=bnds, tol=1e-6
            )
            probability_cali = res.x
        return probability_cali

    def apply_readout_mitigation(self, raw_count: ct, method: str = "inverse") -> ct:
        """
        Main readout mitigation program for method="inverse" or "square"

        :param raw_count: the raw count
        :type raw_count: ct
        :param method: mitigation method, defaults to "inverse"
        :type method: str, optional
        :return: mitigated count
        :rtype: ct
        """
        probability = count2vec(raw_count)
        shots = sum([v for k, v in raw_count.items()])
        probability = self.mitigate_probability(probability, method=method)
        probability = probability * shots
        return vec2count(probability)

    def apply_correction(
        self,
        counts: ct,
        qubits: Sequence[int],
        distance: Optional[int] = None,
        method: str = "square",
        max_iter: int = 25,
        tol: float = 1e-5,
        return_mitigation_overhead: bool = False,
        details: bool = False,
    ) -> ct:
        """
        Main readout mitigation program for all methods.

        :param counts: raw count
        :type counts: ct
        :param qubits: used qubit list
        :type qubits: Sequence[Any]
        :param distance:  defaults to None
        :type distance: int, optional
        :param method: mitigation method, defaults to "square"
        :type method: str, optional
        :param max_iter: defaults to 25
        :type max_iter: int, optional
        :param tol:  defaults to 1e-5
        :type tol: float, optional
        :param return_mitigation_overhead:defaults to False
        :type return_mitigation_overhead: bool, optional
        :param details: defaults to False
        :type details: bool, optional
        :return: mitigated count
        :rtype: ct
        """
        if not is_sequence(qubits):
            qubits = list(range(qubits))  # type: ignore
        self.use_qubits = qubits  # type: ignore
        if not set(self.use_qubits).issubset(set(self.cal_qubits)):  # type: ignore
            raise ValueError(
                "The qubit list used in calculation must included in  the calibration qubit list."
            )

        counts = marginal_count(counts, self.use_qubits)  # type: ignore

        # methods for small system, "global" calibration only fit for those methods.
        if method == "inverse":
            mitcounts = self.apply_readout_mitigation(counts, method="inverse")
            return mitcounts
        elif method == "square":
            mitcounts = self.apply_readout_mitigation(counts, method="square")
            return mitcounts
        if mthree_installed is False:
            warnings.warn(
                " To use [scalable-] related methods, please pip install mthree !"
            )

        if len(counts) == 0:
            raise M3Error("Input counts is any empty dict.")
        given_list = False
        if isinstance(counts, (list, np.ndarray)):
            given_list = True
        if not given_list:
            counts = [counts]  # type: ignore

        if isinstance(qubits, dict):
            # If a mapping was given for qubits
            qubits = [list(qubits)]  # type: ignore
        elif not any(isinstance(qq, (list, tuple, np.ndarray, dict)) for qq in qubits):
            qubits = [qubits] * len(counts)  # type: ignore
        else:
            if isinstance(qubits[0], dict):
                # assuming passed a list of mappings
                qubits = [list(qu) for qu in qubits]  # type: ignore

        if len(qubits) != len(counts):
            raise M3Error("Length of counts does not match length of qubits.")

        quasi_out = []
        for idx, cnts in enumerate(counts):

            quasi_out.append(
                self._apply_correction(
                    cnts,
                    qubits=qubits[idx],
                    distance=distance,
                    method=method,
                    max_iter=max_iter,
                    tol=tol,
                    return_mitigation_overhead=return_mitigation_overhead,
                    details=details,
                )
            )

        if not given_list:
            return quasi_out[0]  # type: ignore
        mitcounts = QuasiCollection(quasi_out)
        return mitcounts.nearest_probability_distribution()  # type: ignore

    def _apply_correction(  # type: ignore
        self,
        counts,
        qubits,
        distance=None,
        method="auto",
        max_iter=25,
        tol=1e-5,
        return_mitigation_overhead=False,
        details=False,
    ):

        # This is needed because counts is a Counts object in Qiskit not a dict.
        counts = dict(counts)
        shots = sum(counts.values())

        # If distance is None, then assume max distance.
        num_bits = len(qubits)
        num_elems = len(counts)
        if distance is None:
            distance = num_bits

        # check if len of bitstrings does not equal number of qubits passed.
        bitstring_len = len(next(iter(counts)))
        if bitstring_len != num_bits:
            raise M3Error(
                "Bitstring length ({}) does not match".format(bitstring_len)
                + " number of qubits ({})".format(num_bits)
            )

        # Check if no cals done yet
        if self.single_qubit_cals is None:
            warnings.warn("No calibration data. Calibrating: {}".format(qubits))
            self._grab_additional_cals(qubits, method=self.cal_method)  # type: ignore

        # Check if one or more new qubits need to be calibrated.
        missing_qubits = [qq for qq in qubits if self.single_qubit_cals[qq] is None]  # type: ignore
        if any(missing_qubits):
            warnings.warn(
                "Computing missing calibrations for qubits: {}".format(missing_qubits)
            )
            self._grab_additional_cals(missing_qubits, method=self.cal_method)  # type: ignore

        if method == "Max1":
            current_free_mem = psutil.virtual_memory().available / 1024**3
            # First check if direct method can be run
            if num_elems <= self.iter_threshold and (
                (num_elems**2 + num_elems) * 8 / 1024**3 < current_free_mem / 2
            ):
                method = "direct"
            else:
                method = "iterative"

        if method == "Max2":
            st = perf_counter()
            mit_counts, col_norms, gamma = self._direct_solver(
                counts, qubits, distance, return_mitigation_overhead
            )
            dur = perf_counter() - st
            mit_counts.shots = shots
            if gamma is not None:
                mit_counts.mitigation_overhead = gamma * gamma
            if details:
                info = {"method": "direct", "time": dur, "dimension": num_elems}
                info["col_norms"] = col_norms
                return mit_counts, info
            return mit_counts

        elif method == "Max3":
            iter_count = np.zeros(1, dtype=int)

            def callback(_):  # type: ignore
                iter_count[0] += 1

            if details:
                st = perf_counter()
                mit_counts, col_norms, gamma = self._matvec_solver(
                    counts,
                    qubits,
                    distance,
                    tol,
                    max_iter,
                    1,
                    callback,
                    return_mitigation_overhead,
                )
                dur = perf_counter() - st
                mit_counts.shots = shots
                if gamma is not None:
                    mit_counts.mitigation_overhead = gamma * gamma
                info = {"method": "iterative", "time": dur, "dimension": num_elems}
                info["iterations"] = iter_count[0]
                info["col_norms"] = col_norms
                return mit_counts, info
            # pylint: disable=unbalanced-tuple-unpacking
            mit_counts, gamma = self._matvec_solver(
                counts,
                qubits,
                distance,
                tol,
                max_iter,
                0,
                None,
                return_mitigation_overhead,
            )
            mit_counts.shots = shots
            if gamma is not None:
                mit_counts.mitigation_overhead = gamma * gamma
            return mit_counts

        else:
            raise M3Error("Invalid method: {}".format(method))

    def reduced_cal_matrix(self, counts, qubits, distance=None):  # type: ignore

        counts = dict(counts)
        # If distance is None, then assume max distance.
        num_bits = len(qubits)
        if distance is None:
            distance = num_bits

        # check if len of bitstrings does not equal number of qubits passed.
        bitstring_len = len(next(iter(counts)))
        if bitstring_len != num_bits:
            raise M3Error(
                "Bitstring length ({}) does not match".format(bitstring_len)
                + " number of qubits ({})".format(num_bits)
            )

        cals = self._form_cals(qubits)
        A, counts, _ = _reduced_cal_matrix(counts, cals, num_bits, distance)
        return A, counts

    def _direct_solver(  # type: ignore
        self, counts, qubits, distance=None, return_mitigation_overhead=False
    ):

        cals = self._form_cals(qubits)
        num_bits = len(qubits)
        A, sorted_counts, col_norms = _reduced_cal_matrix(
            counts, cals, num_bits, distance
        )
        vec = counts_to_vector(sorted_counts)
        LU = la.lu_factor(A, check_finite=False)
        x = la.lu_solve(LU, vec, check_finite=False)
        gamma = None
        if return_mitigation_overhead:
            gamma = ainv_onenorm_est_lu(A, LU)
        out = vector_to_quasiprobs(x, sorted_counts)
        return out, col_norms, gamma

    def _matvec_solver(  # type: ignore
        self,
        counts,
        qubits,
        distance,
        tol=1e-5,
        max_iter=25,
        details=0,
        callback=None,
        return_mitigation_overhead=False,
    ):

        cals = self._form_cals(qubits)
        M = M3MatVec(dict(counts), cals, distance)
        L = spla.LinearOperator(
            (M.num_elems, M.num_elems), matvec=M.matvec, rmatvec=M.rmatvec
        )
        diags = M.get_diagonal()

        def precond_matvec(x):  # type: ignore
            out = x / diags
            return out

        P = spla.LinearOperator((M.num_elems, M.num_elems), precond_matvec)
        vec = counts_to_vector(M.sorted_counts)
        out, error = spla.gmres(
            L, vec, tol=tol, atol=tol, maxiter=max_iter, M=P, callback=callback
        )
        if error:
            raise M3Error("GMRES did not converge: {}".format(error))

        gamma = None
        if return_mitigation_overhead:
            gamma = ainv_onenorm_est_iter(M, tol=tol, max_iter=max_iter)

        quasi = vector_to_quasiprobs(out, M.sorted_counts)
        if details:
            return quasi, M.get_col_norms(), gamma
        return quasi, gamma
