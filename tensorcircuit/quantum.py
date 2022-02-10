"""
quantum state and operator class backend by tensornetwork
"""
# pylint: disable=invalid-name

from functools import reduce, wraps, partial
import logging
from operator import or_, mul, matmul
from typing import (
    Any,
    Callable,
    Collection,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

import numpy as np
from tensornetwork.network_components import AbstractNode, Node, Edge, connect
from tensornetwork.network_components import CopyNode
from tensornetwork.network_operations import get_all_nodes, copy, reachable
from tensornetwork.network_operations import get_subgraph_dangling, remove_node

try:
    import tensorflow as tf
except ImportError:
    pass

from .cons import backend, contractor, dtypestr
from .backends import get_backend  # type: ignore

Tensor = Any
Graph = Any

logger = logging.getLogger(__name__)

# Note the first version of part of this file is adpated from source code of tensornetwork: (Apache2)
# https://github.com/google/TensorNetwork/blob/master/tensornetwork/quantum/quantum.py
# For the reason of adoption instead of direct import: see https://github.com/google/TensorNetwork/issues/950

# TODO(@refraction-ray): docstring to sphinx style in this file...

# general conventions left (first) out, right (then) in


def quantum_constructor(
    out_edges: Sequence[Edge],
    in_edges: Sequence[Edge],
    ref_nodes: Optional[Collection[AbstractNode]] = None,
    ignore_edges: Optional[Collection[Edge]] = None,
) -> "QuOperator":
    """
    Constructs an appropriately specialized QuOperator.
    If there are no edges, creates a QuScalar. If the are only output (input)
    edges, creates a QuVector (QuAdjointVector). Otherwise creates a QuOperator.

    :param out_edges: output edges.
    :type out_edges: Sequence[Edge]
    :param in_edges: in edges.
    :type in_edges: Sequence[Edge]
    :param ref_nodes: reference nodes for the tensor network (needed if there is a
        scalar component).
    :type ref_nodes: Optional[Collection[AbstractNode]], optional
    :param ignore_edges: edges to ignore when checking the dimensionality of the
        tensor network.
    :type ignore_edges: Optional[Collection[Edge]], optional
    :return: The new created QuOperator object.
    :rtype: QuOperator
    """
    if len(out_edges) == 0 and len(in_edges) == 0:
        return QuScalar(ref_nodes, ignore_edges)  # type: ignore
    if len(out_edges) == 0:
        return QuAdjointVector(in_edges, ref_nodes, ignore_edges)
    if len(in_edges) == 0:
        return QuVector(out_edges, ref_nodes, ignore_edges)
    return QuOperator(out_edges, in_edges, ref_nodes, ignore_edges)


def identity(
    space: Sequence[int],
    dtype: Any = np.float64,
) -> "QuOperator":
    """
    Construct a 'QuOperator' representing the identity on a given space.
    Internally, this is done by constructing 'CopyNode's for each edge, with
    dimension according to 'space'.

    :param space: A sequence of integers for the dimensions of the tensor product
        factors of the space (the edges in the tensor network).
    :type space: Sequence[int]
    :param dtype: The data type (for conversion to dense).
    :type dtype: Any type
    :return: The desired identity operator.
    :rtype: QuOperator
    """
    nodes = [CopyNode(2, d, dtype=dtype) for d in space]
    out_edges = [n[0] for n in nodes]
    in_edges = [n[1] for n in nodes]
    return quantum_constructor(out_edges, in_edges)


def check_spaces(edges_1: Sequence[Edge], edges_2: Sequence[Edge]) -> None:
    """
    Check the vector spaces represented by two lists of edges are compatible.
    The number of edges must be the same and the dimensions of each pair of edges
    must match. Otherwise, an exception is raised.
    :param edges_1: List of edges representing a many-body Hilbert space.
    :type edges_1: Sequence[Edge]
    :param edges_2: List of edges representing a many-body Hilbert space.
    :type edges_2: Sequence[Edge]

    :raises ValueError: Hilbert-space mismatch: "Cannot connect {} subsystems with {} subsystems", or
        "Input dimension {} != output dimension {}."
    """
    if len(edges_1) != len(edges_2):
        raise ValueError(
            "Hilbert-space mismatch: Cannot connect {} subsystems "
            "with {} subsystems.".format(len(edges_1), len(edges_2))
        )

    for (i, (e1, e2)) in enumerate(zip(edges_1, edges_2)):
        if e1.dimension != e2.dimension:
            raise ValueError(
                "Hilbert-space mismatch on subsystems {}: Input "
                "dimension {} != output dimension {}.".format(
                    i, e1.dimension, e2.dimension
                )
            )


def eliminate_identities(nodes: Collection[AbstractNode]) -> Tuple[dict, dict]:  # type: ignore
    """
    Eliminates any connected CopyNodes that are identity matrices.
    This will modify the network represented by `nodes`.
    Only identities that are connected to other nodes are eliminated.

    :param nodes: Collection of nodes to search.
    :type nodes: Collection[AbstractNode]
    :return: The Dictionary mapping remaining Nodes to any replacements, Dictionary specifying all dangling-edge
        replacements.
    :rtype: Dict[Union[CopyNode, AbstractNode], Union[Node, AbstractNode]], Dict[Edge, Edge]
    """
    nodes_dict = {}
    dangling_edges_dict = {}
    for n in nodes:
        if (
            isinstance(n, CopyNode)
            and n.get_rank() == 2
            and not (n[0].is_dangling() and n[1].is_dangling())
        ):
            old_edges = [n[0], n[1]]
            _, new_edges = remove_node(n)
            if 0 in new_edges and 1 in new_edges:
                e = connect(new_edges[0], new_edges[1])
            elif 0 in new_edges:  # 1 was dangling
                dangling_edges_dict[old_edges[1]] = new_edges[0]
            elif 1 in new_edges:  # 0 was dangling
                dangling_edges_dict[old_edges[0]] = new_edges[1]
            else:
                # Trace of identity, so replace with a scalar node!
                d = n.get_dimension(0)
                # NOTE: Assume CopyNodes have numpy dtypes.
                nodes_dict[n] = Node(np.array(d, dtype=n.dtype))
        else:
            for e in n.get_all_dangling():
                dangling_edges_dict[e] = e
            nodes_dict[n] = n

    return nodes_dict, dangling_edges_dict


class QuOperator:
    """
    Represents a linear operator via a tensor network.
    To interpret a tensor network as a linear operator, some of the dangling
    edges must be designated as `out_edges` (output edges) and the rest as
    `in_edges` (input edges).
    Considered as a matrix, the `out_edges` represent the row index and the
    `in_edges` represent the column index.
    The (right) action of the operator on another then consists of connecting
    the `in_edges` of the first operator to the `out_edges` of the second.
    Can be used to do simple linear algebra with tensor networks.
    """

    __array_priority__ = 100.0  # for correct __rmul__ with scalar ndarrays

    def __init__(
        self,
        out_edges: Sequence[Edge],
        in_edges: Sequence[Edge],
        ref_nodes: Optional[Collection[AbstractNode]] = None,
        ignore_edges: Optional[Collection[Edge]] = None,
    ) -> None:
        """
        Creates a new `QuOperator` from a tensor network.
        This encapsulates an existing tensor network, interpreting it as a linear
        operator.
        The network is checked for consistency: All dangling edges must either be
        in `out_edges`, `in_edges`, or `ignore_edges`.

        :param out_edges: The edges of the network to be used as the output edges.
        :type out_edges: Sequence[Edge]
        :param in_edges: The edges of the network to be used as the input edges.
        :type in_edges: Sequence[Edge]
        :param ref_nodes: Nodes used to refer to parts of the tensor network that are
            not connected to any input or output edges (for example: a scalar
            factor).
        :type ref_nodes: Optional[Collection[AbstractNode]], optional
        :param ignore_edges: Optional collection of dangling edges to ignore when
            performing consistency checks.
        :type ignore_edges: Optional[Collection[Edge]], optional
        :raises ValueError: At least one reference node is required to specify a scalar. None provided!
        """
        # TODO: Decide whether the user must also supply all nodes involved.
        #       This would enable extra error checking and is probably clearer
        #       than `ref_nodes`.
        if len(in_edges) == 0 and len(out_edges) == 0 and not ref_nodes:
            raise ValueError(
                "At least one reference node is required to specify a "
                "scalar. None provided!"
            )
        self.out_edges = list(out_edges)
        self.in_edges = list(in_edges)
        self.ignore_edges = set(ignore_edges) if ignore_edges else set()
        self.ref_nodes = set(ref_nodes) if ref_nodes else set()
        self.check_network()

    @classmethod
    def from_tensor(
        cls,
        tensor: Tensor,
        out_axes: Optional[Sequence[int]] = None,
        in_axes: Optional[Sequence[int]] = None,
    ) -> "QuOperator":
        """
        Construct a `QuOperator` directly from a single tensor.
        This first wraps the tensor in a `Node`, then constructs the `QuOperator`
        from that `Node`.

        :param tensor: The tensor.
        :type tensor: tensor
        :param out_axes: The axis indices of `tensor` to use as `out_edges`.
        :type out_axes: Optional[Sequence[int]], optional
        :param in_axes: The axis indices of `tensor` to use as `in_edges`.
        :type in_axes: Optional[Sequence[int]], optional
        :return: The new operator.
        :rtype: QuOperator
        """
        nlegs = len(tensor.shape)
        if (out_axes is None) and (in_axes is None):
            out_axes = [i for i in range(int(nlegs / 2))]
            in_axes = [i for i in range(int(nlegs / 2), nlegs)]
        elif out_axes is None:
            out_axes = [i for i in range(nlegs) if i not in in_axes]  # type: ignore
        elif in_axes is None:
            in_axes = [i for i in range(nlegs) if i not in out_axes]
        n = Node(tensor)
        out_edges = [n[i] for i in out_axes]
        in_edges = [n[i] for i in in_axes]  # type: ignore
        return cls(out_edges, in_edges)

    @classmethod
    def from_local_tensor(
        cls,
        tensor: Tensor,
        space: Sequence[int],
        loc: Sequence[int],
        out_axes: Optional[Sequence[int]] = None,
        in_axes: Optional[Sequence[int]] = None,
    ) -> "QuOperator":
        nlegs = len(tensor.shape)
        if (out_axes is None) and (in_axes is None):
            out_axes = [i for i in range(int(nlegs / 2))]
            in_axes = [i for i in range(int(nlegs / 2), nlegs)]
        elif out_axes is None:
            out_axes = [i for i in range(nlegs) if i not in in_axes]  # type: ignore
        elif in_axes is None:
            in_axes = [i for i in range(nlegs) if i not in out_axes]
        localn = Node(tensor)
        out_edges = [localn[i] for i in out_axes]
        in_edges = [localn[i] for i in in_axes]  # type: ignore
        id_nodes = [
            CopyNode(2, d, dtype=tensor.dtype)
            for i, d in enumerate(space)
            if i not in loc
        ]
        for n in id_nodes:
            out_edges.append(n[0])
            in_edges.append(n[1])

        return cls(out_edges, in_edges)

    @property
    def nodes(self) -> Set[AbstractNode]:
        """All tensor-network nodes involved in the operator."""
        return reachable(get_all_nodes(self.out_edges + self.in_edges) | self.ref_nodes)  # type: ignore

    @property
    def in_space(self) -> List[int]:
        return [e.dimension for e in self.in_edges]

    @property
    def out_space(self) -> List[int]:
        return [e.dimension for e in self.out_edges]

    def is_scalar(self) -> bool:
        return len(self.out_edges) == 0 and len(self.in_edges) == 0

    def is_vector(self) -> bool:
        return len(self.out_edges) > 0 and len(self.in_edges) == 0

    def is_adjoint_vector(self) -> bool:
        return len(self.out_edges) == 0 and len(self.in_edges) > 0

    def check_network(self) -> None:
        """
        Check that the network has the expected dimensionality.
        This checks that all input and output edges are dangling and that
        there are no other dangling edges (except any specified in
        `ignore_edges`). If not, an exception is raised.
        """
        for (i, e) in enumerate(self.out_edges):
            if not e.is_dangling():
                raise ValueError("Output edge {} is not dangling!".format(i))
        for (i, e) in enumerate(self.in_edges):
            if not e.is_dangling():
                raise ValueError("Input edge {} is not dangling!".format(i))
        for e in self.ignore_edges:
            if not e.is_dangling():
                raise ValueError(
                    "ignore_edges contains non-dangling edge: {}".format(str(e))
                )

        known_edges = set(self.in_edges) | set(self.out_edges) | self.ignore_edges
        all_dangling_edges = get_subgraph_dangling(self.nodes)
        if known_edges != all_dangling_edges:
            raise ValueError(
                "The network includes unexpected dangling edges (that "
                "are not members of ignore_edges)."
            )

    def adjoint(self) -> "QuOperator":
        """
        The adjoint of the operator.
        This creates a new `QuOperator` with complex-conjugate copies of all
        tensors in the network and with the input and output edges switched.
        """
        nodes_dict, edge_dict = copy(self.nodes, True)
        out_edges = [edge_dict[e] for e in self.in_edges]
        in_edges = [edge_dict[e] for e in self.out_edges]
        ref_nodes = [nodes_dict[n] for n in self.ref_nodes]
        ignore_edges = [edge_dict[e] for e in self.ignore_edges]
        return quantum_constructor(out_edges, in_edges, ref_nodes, ignore_edges)

    def copy(self) -> "QuOperator":
        nodes_dict, edge_dict = copy(self.nodes, False)
        out_edges = [edge_dict[e] for e in self.out_edges]
        in_edges = [edge_dict[e] for e in self.in_edges]
        ref_nodes = [nodes_dict[n] for n in self.ref_nodes]
        ignore_edges = [edge_dict[e] for e in self.ignore_edges]
        return quantum_constructor(out_edges, in_edges, ref_nodes, ignore_edges)

    def trace(self) -> "QuOperator":
        """The trace of the operator."""
        return self.partial_trace(range(len(self.in_edges)))

    def norm(self) -> "QuOperator":
        """
        The norm of the operator.
        This is the 2-norm (also known as the Frobenius or Hilbert-Schmidt
        norm).
        """
        return (self.adjoint() @ self).trace()

    def partial_trace(self, subsystems_to_trace_out: Collection[int]) -> "QuOperator":
        """
        The partial trace of the operator.
        Subsystems to trace out are supplied as indices, so that dangling edges
        are connected to each other as:
          `out_edges[i] ^ in_edges[i] for i in subsystems_to_trace_out`
        This does not modify the original network. The original ordering of the
        remaining subsystems is maintained.

        :param subsystems_to_trace_out: Indices of subsystems to trace out.
        :type subsystems_to_trace_out: Collection[int]
        :return: A new QuOperator or QuScalar representing the result.
        :rtype: QuOperator
        """
        out_edges_trace = [self.out_edges[i] for i in subsystems_to_trace_out]
        in_edges_trace = [self.in_edges[i] for i in subsystems_to_trace_out]

        check_spaces(in_edges_trace, out_edges_trace)

        nodes_dict, edge_dict = copy(self.nodes, False)
        for (e1, e2) in zip(out_edges_trace, in_edges_trace):
            edge_dict[e1] = edge_dict[e1] ^ edge_dict[e2]

        # get leftover edges in the original order
        out_edges_trace = set(out_edges_trace)  # type: ignore
        in_edges_trace = set(in_edges_trace)  # type: ignore
        out_edges = [edge_dict[e] for e in self.out_edges if e not in out_edges_trace]
        in_edges = [edge_dict[e] for e in self.in_edges if e not in in_edges_trace]
        ref_nodes = [n for _, n in nodes_dict.items()]
        ignore_edges = [edge_dict[e] for e in self.ignore_edges]

        return quantum_constructor(out_edges, in_edges, ref_nodes, ignore_edges)

    def __matmul__(self, other: Union["QuOperator", Tensor]) -> "QuOperator":
        """The action of this operator on another.
        Given `QuOperator`s `A` and `B`, produces a new `QuOperator` for `A @ B`,
        where `A @ B` means: "the action of A, as a linear operator, on B".
        Under the hood, this produces copies of the tensor networks defining `A`
        and `B` and then connects the copies by hooking up the `in_edges` of
        `A.copy()` to the `out_edges` of `B.copy()`.
        """
        if not isinstance(other, QuOperator):
            other = self.from_tensor(other)
        check_spaces(self.in_edges, other.out_edges)

        # Copy all nodes involved in the two operators.
        # We must do this separately for self and other, in case self and other
        # are defined via the same network components (e.g. if self === other).
        nodes_dict1, edges_dict1 = copy(self.nodes, False)
        nodes_dict2, edges_dict2 = copy(other.nodes, False)

        # connect edges to create network for the result
        for (e1, e2) in zip(self.in_edges, other.out_edges):
            _ = edges_dict1[e1] ^ edges_dict2[e2]

        in_edges = [edges_dict2[e] for e in other.in_edges]
        out_edges = [edges_dict1[e] for e in self.out_edges]
        ref_nodes = [n for _, n in nodes_dict1.items()] + [
            n for _, n in nodes_dict2.items()
        ]
        ignore_edges = [edges_dict1[e] for e in self.ignore_edges] + [
            edges_dict2[e] for e in other.ignore_edges
        ]

        return quantum_constructor(out_edges, in_edges, ref_nodes, ignore_edges)

    def __rmatmul__(self, other: Union["QuOperator", Tensor]) -> "QuOperator":
        return self.__matmul__(other)

    def __mul__(self, other: Union["QuOperator", AbstractNode, Tensor]) -> "QuOperator":
        """Scalar multiplication of operators.
        Given two operators `A` and `B`, one of the which is a scalar (it has no
        input or output edges), `A * B` produces a new operator representing the
        scalar multiplication of `A` and `B`.
        For convenience, one of `A` or `B` may be a number or scalar-valued tensor
        or `Node` (it will automatically be wrapped in a `QuScalar`).
        Note: This is a special case of `tensor_product()`.
        """
        if not isinstance(other, QuOperator):
            if isinstance(other, AbstractNode):
                node = other
            else:
                node = Node(other)
            if node.shape:
                raise ValueError(
                    "Cannot perform elementwise multiplication by a "
                    "non-scalar tensor."
                )
            other = QuScalar([node])

        if self.is_scalar() or other.is_scalar():
            return self.tensor_product(other)

        raise ValueError(
            "Elementwise multiplication is only supported if at "
            "least one of the arguments is a scalar."
        )

    def __rmul__(
        self, other: Union["QuOperator", AbstractNode, Tensor]
    ) -> "QuOperator":
        """Scalar multiplication of operators.
        See `.__mul__()`.
        """
        return self.__mul__(other)

    def tensor_product(self, other: "QuOperator") -> "QuOperator":
        """
        Tensor product with another operator.
        Given two operators `A` and `B`, produces a new operator `AB` representing
        `A` ⊗ `B`. The `out_edges` (`in_edges`) of `AB` is simply the
        concatenation of the `out_edges` (`in_edges`) of `A.copy()` with that of
        `B.copy()`:
        `new_out_edges = [*out_edges_A_copy, *out_edges_B_copy]`
        `new_in_edges = [*in_edges_A_copy, *in_edges_B_copy]`

        :param other: The other operator (`B`).
        :type other: QuOperator
        :return: The result (`AB`).
        :rtype: QuOperator
        """
        nodes_dict1, edges_dict1 = copy(self.nodes, False)
        nodes_dict2, edges_dict2 = copy(other.nodes, False)

        in_edges = [edges_dict1[e] for e in self.in_edges] + [
            edges_dict2[e] for e in other.in_edges
        ]
        out_edges = [edges_dict1[e] for e in self.out_edges] + [
            edges_dict2[e] for e in other.out_edges
        ]
        ref_nodes = [n for _, n in nodes_dict1.items()] + [
            n for _, n in nodes_dict2.items()
        ]
        ignore_edges = [edges_dict1[e] for e in self.ignore_edges] + [
            edges_dict2[e] for e in other.ignore_edges
        ]

        return quantum_constructor(out_edges, in_edges, ref_nodes, ignore_edges)

    def __or__(self, other: "QuOperator") -> "QuOperator":
        """
        Tensor product of operators.
        Given two operators `A` and `B`, `A | B` produces a new operator representing the
        tensor product of `A` and `B`.
        """
        return self.tensor_product(other)

    def contract(
        self,
        final_edge_order: Optional[Sequence[Edge]] = None,
    ) -> "QuOperator":
        """
        Contract the tensor network in place.
        This modifies the tensor network representation of the operator (or vector,
        or scalar), reducing it to a single tensor, without changing the value.

        :param final_edge_order: Manually specify the axis ordering of the final tensor.
        :type final_edge_order: Optional[Sequence[Edge]], optional
        :return: The present object.
        :rtype: QuOperator
        """
        nodes_dict, dangling_edges_dict = eliminate_identities(self.nodes)
        self.in_edges = [dangling_edges_dict[e] for e in self.in_edges]
        self.out_edges = [dangling_edges_dict[e] for e in self.out_edges]
        self.ignore_edges = set(dangling_edges_dict[e] for e in self.ignore_edges)
        self.ref_nodes = set(nodes_dict[n] for n in self.ref_nodes if n in nodes_dict)
        self.check_network()
        if final_edge_order:
            final_edge_order = [dangling_edges_dict[e] for e in final_edge_order]
            self.ref_nodes = set(
                [contractor(self.nodes, output_edge_order=final_edge_order)]
            )
        else:
            self.ref_nodes = set([contractor(self.nodes, ignore_edge_order=True)])
        return self

    def eval(
        self,
        final_edge_order: Optional[Sequence[Edge]] = None,
    ) -> Tensor:
        """
        Contracts the tensor network in place and returns the final tensor.
        Note that this modifies the tensor network representing the operator.
        The default ordering for the axes of the final tensor is:
          `*out_edges, *in_edges`.
        If there are any "ignored" edges, their axes come first:
          `*ignored_edges, *out_edges, *in_edges`.

        :param final_edge_order: Manually specify the axis ordering of the final tensor.
            The default ordering is determined by `out_edges` and `in_edges` (see above).
        :type final_edge_order: Optional[Sequence[Edge]], optional
        :raises ValueError: Node count '{}' > 1 after contraction!
        :return: The final tensor representing the operator.
        :rtype: Tensor
        """
        if not final_edge_order:
            final_edge_order = list(self.ignore_edges) + self.out_edges + self.in_edges
        self.contract(final_edge_order)
        nodes = self.nodes
        if len(nodes) != 1:
            raise ValueError(
                "Node count '{}' > 1 after contraction!".format(len(nodes))
            )
        return list(nodes)[0].tensor

    def eval_matrix(self, final_edge_order: Optional[Sequence[Edge]] = None) -> Tensor:
        t = self.eval(final_edge_order)
        shape1 = reduce(mul, [e.dimension for e in self.out_edges] + [1])
        shape2 = reduce(mul, [e.dimension for e in self.in_edges] + [1])
        return backend.reshape(t, [shape1, shape2])


class QuVector(QuOperator):
    """Represents a (column) vector via a tensor network."""

    def __init__(
        self,
        subsystem_edges: Sequence[Edge],
        ref_nodes: Optional[Collection[AbstractNode]] = None,
        ignore_edges: Optional[Collection[Edge]] = None,
    ) -> None:
        """
        Constructs a new `QuVector` from a tensor network.
        This encapsulates an existing tensor network, interpreting it as a (column) vector.

        :param subsystem_edges: The edges of the network to be used as the output edges.
        :type subsystem_edges: Sequence[Edge]
        :param ref_nodes: Nodes used to refer to parts of the tensor network that are
            not connected to any input or output edges (for example: a scalar factor).
        :type ref_nodes: Optional[Collection[AbstractNode]], optional
        :param ignore_edges: Optional collection of edges to ignore when performing consistency checks.
        :type ignore_edges: Optional[Collection[Edge]], optional
        """
        super().__init__(subsystem_edges, [], ref_nodes, ignore_edges)

    @classmethod
    def from_tensor(  # type: ignore
        cls,
        tensor: Tensor,
        subsystem_axes: Optional[Sequence[int]] = None,
    ) -> "QuVector":
        """
        Construct a `QuVector` directly from a single tensor.
        This first wraps the tensor in a `Node`, then constructs the `QuVector`
        from that `Node`.

        :param tensor: The tensor for constructing a "QuVector".
        :type tensor: Tensor
        :param subsystem_axes: Sequence of integer indices specifying the order in which
            to interpret the axes as subsystems (output edges). If not specified,
            the axes are taken in ascending order.
        :type subsystem_axes: Optional[Sequence[int]], optional
        :return: The new constructed QuVector from the given tensor.
        :rtype: QuVector
        """
        n = Node(tensor)
        if subsystem_axes is not None:
            subsystem_edges = [n[i] for i in subsystem_axes]
        else:
            subsystem_edges = n.get_all_edges()
        return cls(subsystem_edges)

    @property
    def subsystem_edges(self) -> List[Edge]:
        return self.out_edges

    @property
    def space(self) -> List[int]:
        return self.out_space

    def projector(self) -> "QuOperator":
        return self @ self.adjoint()

    def reduced_density(self, subsystems_to_trace_out: Collection[int]) -> "QuOperator":
        rho = self.projector()
        return rho.partial_trace(subsystems_to_trace_out)


class QuAdjointVector(QuOperator):
    """Represents an adjoint (row) vector via a tensor network."""

    def __init__(
        self,
        subsystem_edges: Sequence[Edge],
        ref_nodes: Optional[Collection[AbstractNode]] = None,
        ignore_edges: Optional[Collection[Edge]] = None,
    ) -> None:
        """
        Constructs a new `QuAdjointVector` from a tensor network.
        This encapsulates an existing tensor network, interpreting it as an adjoint
        vector (row vector).

        :param subsystem_edges: The edges of the network to be used as the input edges.
        :type subsystem_edges: Sequence[Edge]
        :param ref_nodes: Nodes used to refer to parts of the tensor network that are
            not connected to any input or output edges (for example: a scalar factor).
        :type ref_nodes: Optional[Collection[AbstractNode]], optional
        :param ignore_edges: Optional collection of edges to ignore when performing consistency checks.
        :type ignore_edges: Optional[Collection[Edge]], optional
        """
        super().__init__([], subsystem_edges, ref_nodes, ignore_edges)

    @classmethod
    def from_tensor(  # type: ignore
        cls,
        tensor: Tensor,
        subsystem_axes: Optional[Sequence[int]] = None,
    ) -> "QuAdjointVector":
        """
        Construct a `QuAdjointVector` directly from a single tensor.
        This first wraps the tensor in a `Node`, then constructs the `QuAdjointVector` from that `Node`.

        :param tensor: The tensor for consturcting an QuAdjointVector.
        :type tensor: Tensor
        :param subsystem_axes: Sequence of integer indices specifying the order in which
            to interpret the axes as subsystems (input edges). If not specified,
            the axes are taken in ascending order.
        :type subsystem_axes: Optional[Sequence[int]], optional
        :return: The new construted QuAdjointVector give from the given tensor.
        :rtype: QuAdjointVector
        """
        n = Node(tensor)
        if subsystem_axes is not None:
            subsystem_edges = [n[i] for i in subsystem_axes]
        else:
            subsystem_edges = n.get_all_edges()
        return cls(subsystem_edges)

    @property
    def subsystem_edges(self) -> List[Edge]:
        return self.in_edges

    @property
    def space(self) -> List[int]:
        return self.in_space

    def projector(self) -> "QuOperator":
        return self.adjoint() @ self

    def reduced_density(self, subsystems_to_trace_out: Collection[int]) -> "QuOperator":
        rho = self.projector()
        return rho.partial_trace(subsystems_to_trace_out)


class QuScalar(QuOperator):
    """Represents a scalar via a tensor network."""

    def __init__(
        self,
        ref_nodes: Collection[AbstractNode],
        ignore_edges: Optional[Collection[Edge]] = None,
    ) -> None:
        """
        Constructs a new `QuScalar` from a tensor network.
        This encapsulates an existing tensor network, interpreting it as a scalar.

        :param ref_nodes: Nodes used to refer to the tensor network (need not be
            exhaustive - one node from each disconnected subnetwork is sufficient).
        :type ref_nodes: Collection[AbstractNode]
        :param ignore_edges: Optional collection of edges to ignore when performing consistency checks.
        :type ignore_edges: Optional[Collection[Edge]], optional
        """
        super().__init__([], [], ref_nodes, ignore_edges)

    @classmethod
    def from_tensor(cls, tensor: Tensor) -> "QuScalar":  # type: ignore
        """
        Construct a `QuScalar` directly from a single tensor.
        This first wraps the tensor in a `Node`, then constructs the `QuScalar` from that `Node`.

        :param tensor: The tensor for constructing a new QuScalar.
        :type tensor: Tensor
        :return: The new constructed QuScalar from the given tensor.
        :rtype: QuScalar
        """
        n = Node(tensor)
        return cls(set([n]))


def generate_local_hamiltonian(
    *hlist: Sequence[Tensor], matrix_form: bool = True
) -> Union[QuOperator, Tensor]:
    """
    Note: further jit is recommended,
    for large Hilbert space, sparse Hamiltonian is recommended

    :param hlist: [description]
    :type hlist: Sequence[Tensor]
    :param matrix_form: [description], defaults to True
    :type matrix_form: bool, optional
    :return: [description]
    :rtype: Tensor
    """
    hlist = [backend.cast(h, dtype=dtypestr) for h in hlist]  # type: ignore
    hop_list = [QuOperator.from_tensor(h) for h in hlist]
    hop = reduce(or_, hop_list)
    if matrix_form:
        tensor = hop.eval_matrix()
        return tensor
    return hop


try:
    compiled_jit = partial(get_backend("tensorflow").jit, jit_compile=True)

    def heisenberg_hamiltonian(
        g: Graph,
        hzz: float = 1.0,
        hxx: float = 1.0,
        hyy: float = 1.0,
        hz: float = 0.0,
        hx: float = 0.0,
        hy: float = 0.0,
        sparse: bool = True,
    ) -> Tensor:
        n = len(g.nodes)
        ls = []
        weight = []
        for e in g.edges:
            if hzz != 0:
                r = [0 for _ in range(n)]
                r[e[0]] = 3
                r[e[1]] = 3
                ls.append(r)
                weight.append(hzz)
            if hxx != 0:
                r = [0 for _ in range(n)]
                r[e[0]] = 1
                r[e[1]] = 1
                ls.append(r)
                weight.append(hxx)
            if hyy != 0:
                r = [0 for _ in range(n)]
                r[e[0]] = 2
                r[e[1]] = 2
                ls.append(r)
                weight.append(hyy)
        for node in g.nodes:
            if hz != 0:
                r = [0 for _ in range(n)]
                r[node] = 3
                ls.append(r)
                weight.append(hz)
            if hx != 0:
                r = [0 for _ in range(n)]
                r[node] = 1
                ls.append(r)
                weight.append(hx)
            if hy != 0:
                r = [0 for _ in range(n)]
                r[node] = 2
                ls.append(r)
                weight.append(hy)
        ls = tf.constant(ls)
        weight = tf.constant(weight)
        ls = get_backend("tensorflow").cast(ls, dtypestr)
        weight = get_backend("tensorflow").cast(weight, dtypestr)
        if sparse:
            r = PauliStringSum2COO_numpy(ls, weight)
            return _numpy2tf_sparse(r)
        return PauliStringSum2Dense(ls, weight)

    def PauliStringSum2Dense(
        ls: Sequence[Sequence[int]], weight: Optional[Sequence[float]] = None
    ) -> Tensor:
        sparsem = PauliStringSum2COO_numpy(ls, weight)
        sparsem = _numpy2tf_sparse(sparsem)
        densem = get_backend("tensorflow").to_dense(sparsem)
        return densem

    def _tf2numpy_sparse(a: Tensor) -> Tensor:
        return get_backend("numpy").coo_sparse_matrix(
            indices=a.indices,
            values=a.values,
            shape=a.get_shape(),
        )

    def _numpy2tf_sparse(a: Tensor) -> Tensor:
        return get_backend("tensorflow").coo_sparse_matrix(
            indices=np.array([a.row, a.col]).T,
            values=a.data,
            shape=a.shape,
        )

    def PauliStringSum2COO_numpy(
        ls: Sequence[Sequence[int]], weight: Optional[Sequence[float]] = None
    ) -> Tensor:
        # numpy version is 3* faster!

        nterms = len(ls)
        n = len(ls[0])
        s = 0b1 << n
        if weight is None:
            weight = [1.0 for _ in range(nterms)]
        if not (isinstance(weight, tf.Tensor) or isinstance(weight, tf.Variable)):
            weight = tf.constant(weight, dtype=getattr(tf, dtypestr))
        rsparse = get_backend("numpy").coo_sparse_matrix(
            indices=tf.constant([[0, 0]], dtype=tf.int64),
            values=tf.constant([0.0], dtype=weight.dtype),  # type: ignore
            shape=(s, s),
        )
        for i in range(nterms):
            rsparse += _tf2numpy_sparse(PauliString2COO(ls[i], weight[i]))  # type: ignore
            # auto transformed into csr format!!
        return rsparse.tocoo()

    def PauliStringSum2COO(
        ls: Sequence[Sequence[int]], weight: Optional[Sequence[float]] = None
    ) -> Tensor:
        nterms = len(ls)
        n = len(ls[0])
        s = 0b1 << n
        if weight is None:
            weight = [1.0 for _ in range(nterms)]
        if not (isinstance(weight, tf.Tensor) or isinstance(weight, tf.Variable)):
            weight = tf.constant(weight, dtype=getattr(tf, dtypestr))
        rsparse = tf.SparseTensor(
            indices=tf.constant([[0, 0]], dtype=tf.int64),
            values=tf.constant([0.0], dtype=weight.dtype),  # type: ignore
            dense_shape=(s, s),
        )
        for i in range(nterms):
            rsparse = tf.sparse.add(rsparse, PauliString2COO(ls[i], weight[i]))  # type: ignore
            # TODO(@refraction-ray): very slow sparse.add?
        return rsparse

    @compiled_jit
    def PauliString2COO(l: Sequence[int], weight: Optional[float] = None) -> Tensor:
        n = len(l)
        one = tf.constant(0b1, dtype=tf.int64)
        idx_x = tf.constant(0b0, dtype=tf.int64)
        idx_y = tf.constant(0b0, dtype=tf.int64)
        idx_z = tf.constant(0b0, dtype=tf.int64)
        i = tf.constant(0, dtype=tf.int64)
        for j in l:
            # i, j from enumerate is python, non jittable when cond using tensor
            if j == 1:  # xi
                idx_x += tf.bitwise.left_shift(one, n - i - 1)
            elif j == 2:  # yi
                idx_y += tf.bitwise.left_shift(one, n - i - 1)
            elif j == 3:  # zi
                idx_z += tf.bitwise.left_shift(one, n - i - 1)
            i += 1

        if weight is None:
            weight = tf.constant(1.0, dtype=tf.complex64)
        return ps2coo_core(idx_x, idx_y, idx_z, weight, n)

    @compiled_jit
    def ps2coo_core(
        idx_x: Tensor, idx_y: Tensor, idx_z: Tensor, weight: Tensor, nqubits: int
    ) -> Tuple[Tensor, Tensor]:
        dtype = weight.dtype
        s = 0b1 << nqubits
        idx1 = tf.cast(tf.range(s), dtype=tf.int64)
        idx2 = (idx1 ^ idx_x) ^ (idx_y)
        indices = tf.transpose(tf.stack([idx1, idx2]))
        tmp = idx1 & (idx_y | idx_z)
        e = idx1 * 0
        ny = 0
        for i in range(nqubits):
            # if tmp[i] is power of 2 (non zero), then e[i] = 1
            e ^= tf.bitwise.right_shift(tmp, i) & 0b1
            # how many 1 contained in idx_y
            ny += tf.bitwise.right_shift(idx_y, i) & 0b1
        ny = tf.math.mod(ny, 4)
        values = (
            tf.cast((1 - 2 * e), dtype)
            * tf.math.pow(tf.constant(-1.0j, dtype=dtype), tf.cast(ny, dtype))
            * weight
        )
        return tf.SparseTensor(indices=indices, values=values, dense_shape=(s, s))  # type: ignore


except NameError:
    logger.warning(
        "tensorflow is not installed, and sparse Hamiltonian generation utilities are disabled"
    )
    # TODO(@refraction-ray): backend agnostic sparse matrix generation?

# some quantum quatities below


def op2tensor(
    fn: Callable[..., Any], op_argnums: Union[int, Sequence[int]] = 0
) -> Callable[..., Any]:
    if isinstance(op_argnums, int):
        op_argnums = [op_argnums]

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        nargs = list(args)
        for i in op_argnums:  # type: ignore
            if isinstance(args[i], QuOperator):
                nargs[i] = args[i].copy().eval_matrix()
        out = fn(*nargs, **kwargs)
        return out

    return wrapper


@op2tensor
def entropy(rho: Union[Tensor, QuOperator], eps: float = 1e-12) -> Tensor:
    """
    Compute the entropy from the given density matrix ``rho``.

    :param rho: [description]
    :type rho: Union[Tensor, QuOperator]
    :param eps: [description], defaults to 1e-12
    :type eps: float, optional
    :return: [description]
    :rtype: Tensor
    """
    lbd = backend.real(backend.eigh(rho)[0])
    lbd = backend.relu(lbd)
    # we need the matrix anyway for AD.
    entropy = -backend.sum(lbd * backend.log(lbd + eps))
    return backend.real(entropy)


def trace_product(*o: Union[Tensor, QuOperator]) -> Tensor:
    """
    Compute the trace of several inputs ``o`` as tensor or ``QuOperator``.

    .. math ::

        \\mathrm{Tr}(\\prod_i O_i)

    :return: a scalar
    :rtype: Tensor
    """
    prod = reduce(matmul, o)
    if isinstance(prod, QuOperator):
        return prod.trace().eval_matrix()
    return backend.trace(prod)


def reduced_density_matrix(
    state: Union[Tensor, QuOperator],
    cut: Union[int, List[int]],
    p: Optional[Tensor] = None,
) -> Union[Tensor, QuOperator]:
    """
    Compute the reduced density matrix from quantum state ``state``.

    :param state: [description]
    :type state: Tensor
    :param cut: [description]
    :type cut: Union[int, List[int]]
    :param p: [description], defaults to None
    :type p: Optional[Tensor], optional
    :return: [description]
    :rtype: Tensor
    """

    if isinstance(cut, list) or isinstance(cut, tuple) or isinstance(cut, set):
        traceout = list(cut)
    else:
        traceout = [i for i in range(cut)]
    if isinstance(state, QuOperator):
        if p is not None:
            raise NotImplementedError(
                "p arguments is not supported when state is a `QuOperator`"
            )
        return state.partial_trace(traceout)
    if len(state.shape) == 2 and state.shape[0] == state.shape[1]:
        # density operator
        freedomexp = backend.sizen(state)
        # traceout = sorted(traceout)[::-1]
        freedom = int(np.log2(freedomexp) / 2)
        # traceout2 = [i + freedom for i in traceout]
        left = traceout + [i for i in range(freedom) if i not in traceout]
        right = [i + freedom for i in left]
        rho = backend.reshape(state, [2 for _ in range(2 * freedom)])
        rho = backend.transpose(rho, perm=left + right)
        rho = backend.reshape(
            rho,
            [
                2 ** len(traceout),
                2 ** (freedom - len(traceout)),
                2 ** len(traceout),
                2 ** (freedom - len(traceout)),
            ],
        )
        if p is None:
            # for i, (tr, tr2) in enumerate(zip(traceout, traceout2)):
            #     rho = backend.trace(rho, axis1=tr, axis2=tr2 - i)
            # correct but tf trace fail to support so much dimension with tf.einsum

            rho = backend.trace(rho, axis1=0, axis2=2)
        else:
            p = backend.reshape(p, [-1])
            rho = backend.einsum("a,aiaj->ij", p, rho)
            # raise NotImplementedError(
            #     "p arguments is not supported when state is a density matrix"
            # )
            # TODO(@refraction-ray): implement this
        rho = backend.reshape(
            rho, [2 ** (freedom - len(traceout)), 2 ** (freedom - len(traceout))]
        )
        rho /= backend.trace(rho)

    else:
        w = state / backend.norm(state)
        freedomexp = backend.sizen(state)
        freedom = int(np.log(freedomexp) / np.log(2))
        perm = [i for i in range(freedom) if i not in traceout]
        perm = perm + traceout
        w = backend.reshape(w, [2 for _ in range(freedom)])
        w = backend.transpose(w, perm=perm)
        w = backend.reshape(w, [-1, 2 ** len(traceout)])
        if p is None:
            rho = w @ backend.adjoint(w)
        else:
            rho = w @ backend.diagflat(p) @ backend.adjoint(w)
            rho /= backend.trace(rho)
    return rho


def free_energy(
    rho: Union[Tensor, QuOperator],
    h: Union[Tensor, QuOperator],
    beta: float = 1,
    eps: float = 1e-12,
) -> Tensor:
    energy = backend.real(trace_product(rho, h))
    s = entropy(rho, eps)
    return backend.real(energy - s / beta)


def renyi_entropy(rho: Union[Tensor, QuOperator], k: int = 2) -> Tensor:
    s = 1 / (1 - k) * backend.real(backend.log(trace_product(*[rho for _ in range(k)])))
    return s


def renyi_free_energy(
    rho: Union[Tensor, QuOperator],
    h: Union[Tensor, QuOperator],
    beta: float = 1,
    k: int = 2,
) -> Tensor:
    energy = backend.real(trace_product(rho, h))
    s = renyi_entropy(rho, k)
    return backend.real(energy - s / beta)


def taylorlnm(x: Tensor, k: int) -> Tensor:
    dtype = x.dtype
    s = x.shape[-1]
    y = 1 / k * (-1) ** (k + 1) * backend.eye(s, dtype=dtype)
    for i in reversed(range(k)):
        y = y @ x
        if i > 0:
            y += 1 / (i) * (-1) ** (i + 1) * backend.eye(s, dtype=dtype)
    return y


def truncated_free_energy(
    rho: Tensor, h: Tensor, beta: float = 1, k: int = 2
) -> Tensor:
    dtype = rho.dtype
    s = rho.shape[-1]
    tyexpand = rho @ taylorlnm(rho - backend.eye(s, dtype=dtype), k - 1)
    renyi = -backend.real(backend.trace(tyexpand))
    energy = backend.real(trace_product(rho, h))
    return energy - renyi / beta


@partial(op2tensor, op_argnums=(0, 1))
def trace_distance(rho: Tensor, rho0: Tensor, eps: float = 1e-12) -> Tensor:
    d2 = rho - rho0
    d2 = backend.adjoint(d2) @ d2
    lbds = backend.real(backend.eigh(d2)[0])
    lbds = backend.relu(lbds)
    return 0.5 * backend.sum(backend.sqrt(lbds + eps))


@partial(op2tensor, op_argnums=(0, 1))
def fidelity(rho: Tensor, rho0: Tensor) -> Tensor:
    rhosqrt = backend.sqrtmh(rho)
    return backend.real(backend.trace(backend.sqrtmh(rhosqrt @ rho0 @ rhosqrt)) ** 2)


@op2tensor
def gibbs_state(h: Tensor, beta: float = 1) -> Tensor:
    rho = backend.expm(-beta * h)
    rho /= backend.trace(rho)
    return rho


@op2tensor
def double_state(h: Tensor, beta: float = 1) -> Tensor:
    rho = backend.expm(-beta / 2 * h)
    state = backend.reshape(rho, [-1])
    norm = backend.norm(state)
    return state / norm


@op2tensor
def mutual_information(s: Tensor, cut: Union[int, List[int]]) -> Tensor:
    if isinstance(cut, list) or isinstance(cut, tuple) or isinstance(cut, set):
        traceout = list(cut)
    else:
        traceout = [i for i in range(cut)]

    if len(s.shape) == 2 and s.shape[0] == s.shape[1]:
        # mixed state
        n = int(np.log2(backend.sizen(s)) / 2)
        hab = entropy(s)

        # subsystem a
        rhoa = reduced_density_matrix(s, traceout)
        ha = entropy(rhoa)

        # need subsystem b as well
        other = tuple(i for i in range(n) if i not in traceout)
        rhob = reduced_density_matrix(s, other)  # type: ignore
        hb = entropy(rhob)

    # pure system
    else:
        hab = 0.0
        rhoa = reduced_density_matrix(s, traceout)
        ha = hb = entropy(rhoa)

    return ha + hb - hab


def measurement_counts(
    state: Tensor, counts: int = 8192, sparse: bool = True
) -> Union[Tuple[Tensor, Tensor], Tensor]:
    """
    Simulate the measuring of each qubit of ``p`` in the computational basis,
    thus producing output like that of ``qiskit``.

    :param state: The quantum state, assumed to be normalized, as either a ket or density operator.
    :type state: Tensor
    :param counts: The number of counts to perform.
    :type counts: int
    :param sparse: The bool indicating whether the return form is sparse.
    :type sparse: bool
    :return: The counts for each bit string measured.
    :rtype: Tuple[]
    """
    if len(state.shape) == 2:
        state /= backend.trace(state)
        pi = backend.real(backend.diagonal(state))
    else:
        state /= backend.norm(state)
        pi = backend.real(backend.conj(state) * state)
    pi = backend.reshape(pi, [-1])
    d = int(pi.shape[0])
    # raw counts in terms of integers
    raw_counts = backend.implicit_randc(d, shape=counts, p=pi)
    results = backend.unique_with_counts(raw_counts)
    if sparse:
        return results  # type: ignore
    dense_results = backend.scatter(
        backend.cast(backend.zeros([d]), results[1].dtype),
        backend.reshape(results[0], [-1, 1]),
        results[1],
    )
    return dense_results


def spin_by_basis(n: int, m: int, elements: Tuple[int, int] = (1, -1)) -> Tensor:
    s = backend.tile(
        backend.cast(
            backend.convert_to_tensor(np.array([[elements[0]], [elements[1]]])), "int32"
        ),
        [2 ** m, int(2 ** (n - m - 1))],
    )
    return backend.reshape(s, [-1])


def correlation_from_counts(index: Sequence[int], results: Tensor) -> Tensor:
    results = backend.reshape(results, [-1])
    n = int(np.log(results.shape[0]) / np.log(2))
    for i in index:
        results = results * backend.cast(spin_by_basis(n, i), results.dtype)
    return backend.sum(results)


# @op2tensor
# def purify(rho):
#     """
#     Take state rho and purify it into a wavefunction of squared dimension.
#     """
#     d = rho.shape[0]
#     evals, vs = backend.eigh(rho)
#     evals = backend.relu(evals)
#     psi = np.zeros(shape=(d ** 2, 1), dtype=complex)
#     for i, lbd in enumerate(lbd):
#         psi += lbd * kron(vs[:, [i]], basis_vec(i, d))
#     return psi
