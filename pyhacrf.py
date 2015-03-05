# Authors: Dirko Coetsee
# License: 3-clause BSD

""" Implements a Hidden Alignment Conditional Random Field (HACRF). """

import numpy as np
from scipy.optimize import fmin_l_bfgs_b
from collections import defaultdict


class Hacrf(object):
    """ Hidden Alignment Conditional Random Field with L2 regularizer.

    See *A Conditional Random Field for Discriminatively-trained Finite-state String Edit Distance* by McCallum, Bellare, and Pereira,
        and the report *Conditional Random Fields for Noisy text normalisation* by Dirko Coetsee.
    """

    def __init__(self):
        self._optimizer_result = None
        self.parameters = None

    def fit(self, X, y):
        """Fit the model according to the given training data.

        Parameters
        ----------
        X : List of ndarrays, one for each training example.
            Each training example's shape is (string1_len, string2_len, n_features, where
            string1_len and string2_len are the length of the two training strings and n_features the
            number of features.

        y : array-like, shape (n_samples,)
            Target vector relative to X.

        Returns
        -------
        self : object
            Returns self.
        """
        classes = list(set(y))
        n_points = len(y)
        if len(X) != n_points:
            raise Exception('Number of training points should be the same as training labels.')

        # Default state machine. Tuple (list_of_states, list_of_transitions)
        state_machine, states_to_classes = self._default_state_machine(classes)

        # Initialize the parameters given the state machine, features, and target classes.
        self.parameters = self._initialize_parameters(state_machine, X[0].shape[2])

        # Create a new model object for each training example
        models = [_Model(state_machine, classes, x, ty) for x, ty in zip(X, y)]

        derivative = np.zeros(self.parameters.shape)

        def _objective(parameters):
            derivative.fill(0.0)
            ll = 0.0  # Log likelihood
            # TODO: Embarrassingly parallel
            for model in models:
                model.forward_backward(parameters)
                model.add_derivative(derivative)
                ll += model.ll
            return -ll, -derivative

        self._optimizer_result = fmin_l_bfgs_b(_objective, self.parameters)
        return self

    def predict_proba(self):
        pass

    def predict(self):
        pass

    @staticmethod
    def _initialize_parameters(state_machine, n_features):
        """ Helper to create initial parameter vector with the correct shape. """
        n_states = len(state_machine[0])
        n_transitions = len(state_machine[1])
        return np.zeros((n_features, n_states + n_transitions))

    @staticmethod
    def _default_state_machine(classes):
        """ Helper to construct a state machine that includes insertions, matches, and deletions for each class. """
        n_classes = len(classes)
        return (([tuple(i for i in xrange(n_classes))],  # A state for each class. In tuple because they are all start states.
                 [(i, i, (1, 1)) for i in xrange(n_classes)] +  # Match
                 [(i, i, (0, 1)) for i in xrange(n_classes)] +  # Insertion
                 [(i, i, (1, 0)) for i in xrange(n_classes)]),  # Deletion
                dict((i, c) for i, c in enumerate(classes)))


class _Model(object):
    """ The actual model that implements the inference routines. """
    def __init__(self, state_machine, classes, x, y):
        self.state_machine = state_machine
        self.classes = classes
        self.x = x
        self.y = y
        self._lattice = self._build_lattice(self.x, self.state_machine)

    def forward_backward(self, parameters):
        """ Run the forward backward algorithm with the given parameters. """
        alpha = defaultdict(float)
        for node in self._lattice:
            if len(node) < 3:
                i, j, s = node
                alpha[node] += np.exp(np.dot(self.x[i, j, :], parameters[:, s]))
            else:
                i0, j0, i1, j1, s0, s1, edge_parameter_index = node  # Actually an edge in this case
                # Use the features at the destination of the edge.
                edge_potential = np.exp(np.dot(self.x[i1, j1, :], parameters[:, edge_parameter_index])
                                        * alpha[(i0, j0, s0)])
                alpha[node] = edge_potential
                alpha[(i1, j1, s1)] += edge_potential

    @staticmethod
    def _build_lattice(x, state_machine):
        """ Helper to construct the list of nodes and edges. """
        I, J, _ = x.shape
        lattice = []
        states, transitions = state_machine
        # Add start states
        assert(isinstance(states[0], tuple))
        unvisited_nodes = [(0, 0, s) for s in states[0]]
        n_states = len(states) - 1 + len(states[0])

        while unvisited_nodes:
            i, j, s = unvisited_nodes.pop(0)
            lattice.append((i, j, s))
            for transition_index, (s0, s1, delta) in enumerate(transitions):
                if s == s0:
                    if callable(delta):
                        di, dj = delta(i, j, x)
                    else:
                        di, dj = delta
                    if i + di < I and j + dj < J:
                        lattice.append((i, j, i + di, j + dj, s0, s1, transition_index + n_states))
                        unvisited_nodes.append((i + di, j + dj, s1))

        return sorted(lattice)


