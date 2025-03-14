# Change Log

## Unreleased

### Added

- Add `c.probability()` method to return probability amplitude

- Add results module including funtionalities on count dict manipulation and readout error mitigation

### Fixed

- Fix adjoint possible bug with agnostic backend

- Fix `sigmoid` bug on pytorch backend

## 0.6.0

### Added

- Add native support for `rxx`, `ryy` and `rzz` gates for translation from qiskit

- Add `from_openqasm` and `from_openqasm_file` methods for `Circuit`

- Add `circuit_params` argument for translation from qiskit to make the interface universal and consistent with other `from_` methods

- Add `shifts` tuple parameter for `experimental.parameter_shift_grad` API so that we can also customize finite difference gradient from this method

- Add `std` method for backends

- Add `NoiseModel` class to programmably configure the global error model when simulating the quantum circuit

- Add `tc.channels.composedkraus` to compose the different Kraus operators as a new one

- Add direct support for noise model via `sample_expectation_ps` and `expectation` methods, both Monte Carlo trajectory and density matrix evolution approaches are supported

### Changed

- Improve the efficiency of `sample_expectation_ps` method by using cached state

### Fixed

- Fixed `unitary_kraus` of Circuit class support for multi-qubit kraus channels, previous implementation fails to reshape the multi-qubit kraus tensor as matrix

- Fixed `kraus_to_super_gate` bug when multi-qubit kraus channels are presented on tensorflow backend

## 0.5.0

### Added

- Finished quantum noise modeling and simulation development stage 1. Add more quantum channels and the differentiable transformation between different channel forms. Add readout error support for sample and sample_expectation_ps methods.

- Add new parameter shift gradient API that supports finite measurement shots and the corresponding example scripts

- Add openqasm format transformation method `c.to_openqasm()`

- Add native support for `phase` and `cphase` gates when transforming to qiskit

- Add native support for `rxx`, `ryy`, `rzz` and `u`, `cu` gates when transforming to qiskit

- Add native support for `u` gate when transforming from qiskit

- Add circuit `from_qsim_file` method to load Google random circuit structure

- Add `searchsorted` method for backend

- Add `probability_sample` method for backend as an alternative for `random_choice` since it supports `status` as external randomness format

- Add `status` support for `sample` and `sample_expection_ps` methods

### Changed

- The inner mechanism for `sample_expectation_ps` is changed to sample representation from count representation for a fast speed

### Fixed

- Fixed the breaking change introduced in jax 0.3.18, `jax._src` is no longer imported into the from the public jax namespace.

- `tc.quantum.correlation_from_samples` now fix the sign error with odd number of spins

- Updated to the latest version of mypy and get rid of lots of type: ignored

- Fix the dtype bug when float is pass to u gate or phase gate

- Fix to qiskit bug when parameterized gate has default nonset parameters

- Fix `iswap` gate translation to qiskit with support for parameters

## 0.4.1

### Added

- Add support for weighted graph QAOA in `tc.templates.blocks.QAOA_block`

- Add `AbstractCircuit` to and from json capability (experimental support, subject to change)

- Add alias for `sd` and `td` gate

- Add `phase` gate and `cphase` gate for the circuit

- Add U gate and CU gate following OpenQASM 3.0 convention

- Add `tc.gates.get_u_parameter` to solve the three Euler angle for the U gate given the matrix

- Add `GateVF.ided()` method to kron quantum gate with identity gate

- Add `batched_parameters_structures.py` example to demonstrate nested vmap and architecture search possibility

- Add `gate_count` method on `AbstractCircuit` to count gates of given type in the circuit

- Add `gate_summary` method on `AbstractCircuit` to count gate by type as a dict

- Add ccx as another alias for toffoli gate

### Changed

- Seperate channel auto register for circuit class with unitary and general case

- The old standalone depolarizing implementation can now be called via `c.depolarizing_reference`

### Fixed

- Move `iswap` gate to vgates list

- Fix possible bug when vmap is nested in different order (only affect tensorflow backend)

- Fix bug when multi input function accept the same variable in different args and gradient or jvp/vjp is required (only affect tensorflow backend)

- Fix the use of rev over rev jacobian for hessian method and back to the efficient solution of fwd over rev order due to the solution of nested vmap issue on tf backend

- Identify potential bug in `unitary_kraus2` implementation, change to `unitary_kraus` instead

## 0.4.0

### Added

- Add `sample_expectation_ps` method for `BaseCircuit`, which measure the Pauli string expectation considering measurement shots

- Add alias `expps` for `expectation_ps` and `sexpps` for `sampled_expectation_ps`

- Add `counts_d2s` and `counts_s2d` in quantum module to transform different representation of measurement shots results

- Add vmap enhanced `parameter_shift_grad` in experimental module (API subjects to change)

- Add `parameter_shift.py` script in examples showcasing how to use parameter shift grad wrapper

- Add `vmap_randomness.py` script in examples showcasing how to vmap external random generators

- Add `noise_sampling_jit.py` script showcasing how real device simulation with sample method is efficiently implemented with Monte Carlo and jit

- Add jit support and external random management for `tc.quantum.measurement_counts`

- Add MPO gate support for multiple qubit gates in `MPSCircuit` simulator

- Add the `expectation_ps` method to `MPSCircuit` (moving to `AbstractCircuit`)

- Add six format of measurement results support and their transformation in quantum module

- Add format option in `Circuit.sample` while maintain the backward compatibility

- Add `tc.utils.arg_alias` which is a decorator that adds alias argument for function with the doc fixed accordingly

- Add quantum channel auto resgisteration method in `Circuit` class

### Changed

- `rxx`, `ryy`, `rzz` gates now has 1/2 factor before theta consitent with `rx`, `ry`, `rz` gates. (breaking change)

- replace `status` arguments in `sample` method as `random_generator` (new convention: status for 0, 1 uniform randomness and random_generator for random key) (breaking change)

- Rewrite the expectation method of `MPSCircuit` to make it general

- Adjusted the initialization method for `MPSCircuit` (move the from_wavefunction method and allow QuVector input) (breaking change)

- `tc.quantum.measurement_counts` aliased as `tc.quantum.measurement_results` and change the function arguments (breaking change)

- Refactor backend to use multiple inheritance approach instead of reflection method

### Fixed

- Add jit support for `sample` method when `allow_state=True`

- Fix the bug that 128 type is converted to 64 value

- Fix `arg_alias` bug when the keyword arguments is None by design

- Fix `arg_alias` when the docstring for each argument is in multiple lines

- Noise channel apply methods in `DMCircuit` can also absorb `status` keyword (directly omitting it) for a consistent API with `Circuit`

## 0.3.1

### Added

- Add overload of plus sign for TensorFlow SparseTensor

- Add support of dict or list of tensors as the input for `tc.KerasLayer`

- Add support of multiple tensor inputs for `tc.TorchLayer`

- Both gate index and `expectation(_ps)` now support negative qubit index, eg. `c.H(-1)` with the same meaning as numpy indexing

- Add `tc.templates.measurements.parameterized_local_measurements` for local Pauli string evaluation

### Changed

- Change pytest xdist option in check_all.sh to `-n auto`

- Further refactor the circuit abstraction as AbstractCircuit and BaseCircuit

### Fixed

- Add `sgates`, `vgates`, `mpogates` and `gate_aliases` back to `BaseCircuit` for backward compatibility

- Add auto conversion of dtype for `unitary` gate

## 0.3.0

### Added

- Add `device` and `device_move` methods on backend with universal device string representation

- Add `to_qir`, `from_qir`, `to_circuit`, `inverse`, `from_qiskit`, `to_qiskit`, `sample`, `prepend`, `append`, `cond_measurment`, `select_gate` method for `DMCircuit` class

- Add `status` arguments as external randomness for `perfect_sampling` and `measure` methods

- `DMCircuit` now supports `mps_inputs` and `mpo_dminputs`

- Add decorator `tc.interfaces.args_to_tensor` to auto convert function inputs as tensor format

### Changed

- Refactor circuit and dmcircuit with common methods now in `basecircuit.py`, and merge dmcircuit.py and dmcircuit2.py, now `DMCircuit` supports MPO gate and qir representation

### Fixed

- Patially solve the issue with visualization on `cond_measure` (#50)

## 0.2.2

### Added

- PyTorch backend support multi pytrees version of `tree_map`

- Add `dtype` backend method which returns the dtype string

- Add TensorFlow interface

- Add `to_dlpack` and `from_dlpack` method on backends

- Add `enable_dlpack` option on interfaces and torchnn

- Add `inverse` method for Circuit (#26)

### Changed

- Refactor `interfaces` code as a submodule and add pytree support for args

- Change the way to register global setup internally, so that we can skip the list of all submodules

- Refactor the tensortrans code to a pytree perspective

### Fixed

- Fixed `numpy` method bug in pytorch backend when the input tensor requires grad (#24) and when the tensor is on GPU (#25)

- Fixed `TorchLayer` parameter list auto registeration

- Pytorch interface is now device aware (#25)

## 0.2.1

### Added

- Add `enable_lightcone` option in circuit `expectation` method, where only gates within casual lightcone of local observable is contracted.

- Add `benchmark` function into utils

### Fixed

- Fixed a vital bug on circuit expectation evaluation, a wrongly transposed operator connection is fixed.

- Name passed in gate application now works as Node name

## 0.2.0

### Added

- Add PyTorch nn Module wrapper in `torchnn`

- Add `reverse`, `mod`, `left_shift`, `right_shift`, `arange` methods on backend

- Brand new `sample` API with batch support and sampling from state support

- add more methods in global namespace, and add alias `KerasLayer`/`TorchLayer`

### Fixed

- Fixed bug in merge single gates when all gates are single-qubit ones

### Changed

- The default contractor enable preprocessing feature where single-qubit gates are merged firstly

## 0.1.3

### Added

- Add more type auto conversion for `tc.gates.Gate` as inputs

- Add `tree_flatten` and `tree_unflatten` method on backends

- Add torch optimizer to the backend agnostic optimizer abstraction

### Changed

- Refactor the tree utils, add native torch support for pytree utils

### Fixed

- grad in torch backend now support pytrees

- fix float parameter issue in translation to qiskit circuit (#19)

## 0.1.2

### Added

- Add `rxx`, `ryy` and `rzz` gate

### Fixed

- Fix installation issue with tensorflow requirements on MACOS with M1 chip

- Improve M1 macOS compatibility with unjit tensorflow ops

- Fixed SVD backprop bug on jax backend of wide matrix

- `mps_input` dtype auto correction enabled

## 0.1.1

### Added

- Add `quoperator` method to get `QuOperator` representation of the circuit unitary

- Add `coo_sparse_matrix_from_numpy` method on backend, where the scipy coo matrix is converted to sparse tensor in corresponding backend

- Add sparse tensor to scipy coo matrix implementation in `numpy` method

### Changed

- `tc.quantum.PauliStringSum2COO`, `tc.quantum.PauliStringSum2Dense`, and `tc.quantum.heisenberg_hamiltonian` now return the tensor in current backend format if `numpy` option sets to False. (Breaking change: previously, the return are fixed in TensorFlow format)

## 0.1.0

### Added

- `DMCircuit` also supports array instead of gate as the operator

### Fixed

- fix translation issue to qiskit when the input parameter is in numpy form

- type conversion in measure API when high precision is set

- fix bug in to_qiskit with new version qiskit

## 0.0.220509

### Added

- Add `eigvalsh` method on backend

### Changed

- `post_select` method return the measurement result int tensor now, consistent with `cond_measure`

- `Circuit.measure` now point to `measure_jit`

## 0.0.220413

### Added

- Add `expectation_ps` method for `DMCircuit`

- Add `measure` and `sample` for `DMCircuit`

### Fixed

- With `Circuit.vis_tex`, for the Circuit has customized input state, the default visualization is psi instead of all zeros now

- `general_kraus` is synced with `apply_general_kraus` for `DMCircuit`

- Fix dtype incompatible issue in kraus methods between status and prob

## 0.0.220402

### Added

- add `utils.append` to build function pipeline

- add `mean` method on backends

- add trigonometric methods on backends

- add `conditional_gate` to support quantum ops based on previous measurment results

- add `expectation_ps` as shortcut to get Pauli string expectation

- add `append` and `prepend` to compose circuits

- add `matrix` method to get the circuit unitary matrix

### Changed

- change the return information of `unitary_kraus` and `general_kraus` methods

- add alias for any gate as unitary

## 0.0.220328

### Added

- add QuOperator convert tools which can convert MPO in the form of TensorNetwork and Quimb into MPO in the form of QuOperator

### Changed

- quantum Hamiltonian generation now support the direct return of numpy form matrix

### Fixed

- unitary_kraus and general_kraus API now supports the mix input of array and Node as kraus list

## 0.0.220318

### Added

- add gradient free scipy interface for optimization

- add qiskit circuit to tensorcircuit circuit methods

- add draw method on circuit from qiskit transform pipeline

### Changed

- futher refactor VQNHE code in applications

- add alias `sample` for `perfect_sampling` method

- optimize VQNHE pipeline for a more stable training loop (breaking changes in some APIs)

### Fixed

- Circuit inputs will convert to tensor first

## 0.0.220311

### Added

- add sigmoid method on backends

- add MPO expectation template function for MPO evaluation on circuit

- add `operator_expectation` in templates.measurements for a unified expectation interface

- add `templates.chems` module for interface between tc and openfermion on quantum chemistry related tasks

- add tc.Circuit to Qiskit QuantumCircuit transformation

### Fixed

- fix the bug in QuOperator.from_local_tensor where the dtype should always be in numpy context

- fix MPO copy when apply MPO gate on the circuit

### Changed

- allow multi-qubit gate in multicontrol gate

## 0.0.220301

### Added

- new universal contraction analyse tools and pseudo contraction rehearsals for debug

- add `gather1d` method on backends for 1d tensor indexing

- add `dataset` module in template submodule for dataset preprocessing and embedding

- MPO format quantum gate is natively support now

- add multicontrol gates in MPO format

### Fixed

- fixed real operation on some methods in templates.measurements

### Changed

- add gatef key in circuit IR dict for the gate function, while replace gate key with the gate node or MPO (breaking change)

## 0.0.220126

### Added

- add `td` and `sd` gates for dagger version of T gate and S gate

- add `argmax` and `argmin` as backend methods

- add `expectation_before` methods for `tc.Circuit` for further manipulation on the tensornetwork

### Changed

- refined repr for `tc.gates.Gate`

- expectation API now supports int index besides list indexes

### Fixed

- make consistent `Gate` return for channels

- fixed bug on list optimizer for contraction

- stability for QR operator in terms of automatic differentiation

## 0.0.220118

### Added

- add `hessian` method on backends

- add further automatic pipelines for visualization by generating pdf or images

- add `reshape2` method on backends as a short cut to reshape a tensor with all legs 2-d

- add `reshapem` method on backends to reshape any tensor as a square matrix

- add `controlled` and `ocontrolled` API to generate more gates

- add `crx`, `cry`, `crz` gate on `Circuit`

- add `__repr__` and `__str__` for backend object

- `tc.expectation` now support ket arg as quvector form

### Fixed

- `sizen` correctly returns 1 for tensor of no shape

- fixed `convert_to_tensor` bug in numpy backend in TensorNetwork

- `any_gate` also support Gate format instead of matrix

- `matrix_for_gate` works now for backends more than numpy

### Changed

- `expectation` API now also accepts plain tensor instead of `tc.Gate`.

- `DMCircuit` and `DMCircuit2` are all pointing the efficent implementations (breaking changes)

## 0.0.220106

### Added

- add `solve` method on backends to solve linear equations

- add full quantum natural gradient examples and `qng` method in experimental module

- add `concat` method to backends

- add `stop_gradient` method to backends

- add `has_aux` arg on `vvag` method

- add `imag` method on backends

- add `Circuit.vis_tex` interface that returns the quantikz circuit latex

### Changed

- contractor, dtype and backend set are default to return objects, `with tc.runtime_backend("jax") as K` or `K = tc.set_backend("jax")` could work

- change `perfect_sampling` to use `measure_jit` behind the scene

- `anygate` automatically reshape the unitary input to 2-d leg for users' good

- `quantum.renyi_entropy` computation with correct prefactor

- `Circuit` gate can provided other names by name attr

- `example_block` support param auto reshape for users' good

### Fixed

- make four algorithms for quantum natural gradient consistent and correct

- torch `real` is now a real

## 0.0.211223

### Added

- add `quantum.heisenberg_hamiltonian` for hamiltonian generation shortcut

- add `has_aux` parameter in backend methods `grad` and `value_and_grad`, the semantic syntax is the same as jax

- add `optimizer` class on tensorflow and jax backend, so that a minimal and unified backend agnostic optimizer interface is provided

- add `quantum.mutual_information`, add support on mixed state for `quantum.reduced_density_matrix`

- add `jvp` methods for tensorflow, jax, torch backends, and ensure pytree support in `jvp` and `vjp` interfaces for tensorflow and jax backends; also ensure complex support for `jvp` and `vjp`

- add `jacfwd` and `jacrev` for backend methods (experimental API, may have bugs and subject to changes)

### Fixed

- fix `matmul` bug on tensornetwork tensorflow backend

### Changed

- delete `qcode` IR for `Circuit`, use `qir` instead (breaking changes)

- basic circuit running is ok on pytorch backend with some complex support fixing

## 0.0.211216

### Added

- add `get_random_state` and `random_split` methods to backends

- add qir representation of circuit, `c.to_qir()` and `Circuit.from_qir()` methods

- fine-grained control on backend, dtype and contractor setup: `tc.set_function_backend()` for function level decorator and `tc.runtime_backend()` as with context manager

- add `state_centric` decorator in `tc.templates.blocks` to transform circuit-to-circuit funtion to state-to-state function

- add `interfaces.scipy_optimize_interface` to transform quantum function into `scipy.optimize.minimize` campatible form

### Fixed

- avoid error on watch non `tf.Tensor` in tensorflow backend grad method

- circuit preprocessing simplification with only single qubit gates

- avoid the bug when random from jax backend with jitted function

- refresh the state cache in Circuit when new gate is applied

### Changed

- refactor `tc.gates` (breaking API on `rgate` -> `r_gate`, `iswapgate` -> `iswap_gate`)
