import os
import pytest
import re

import numpy as np
from casadi import MX, SX, vertcat
from bioptim import (
    VariableScalingList,
    ConfigureProblem,
    DynamicsFunctions,
    BiorbdModel,
    ControlType,
    RigidBodyDynamics,
    NonLinearProgram,
    DynamicsFcn,
    Dynamics,
    DynamicsEvaluation,
    ConstraintList,
    ParameterList,
    PhaseDynamics,
)

from tests.utils import TestUtils


class OptimalControlProgram:
    def __init__(self, nlp):
        self.cx = nlp.cx
        self.phase_dynamics = PhaseDynamics.SHARED_DURING_THE_PHASE
        self.n_phases = 1
        self.nlp = [nlp]
        self.parameters = ParameterList()
        self.implicit_constraints = ConstraintList()
        self.n_threads = 1


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_external_force", [False, True])
@pytest.mark.parametrize("with_contact", [False, True])
@pytest.mark.parametrize(
    "rigidbody_dynamics",
    [RigidBodyDynamics.ODE, RigidBodyDynamics.DAE_FORWARD_DYNAMICS, RigidBodyDynamics.DAE_INVERSE_DYNAMICS],
)
def test_torque_driven(with_contact, with_external_force, cx, rigidbody_dynamics, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)

    nlp.x_bounds = np.zeros((nlp.model.nb_q * 3, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    external_forces = (
        [
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.374540118847362,
                            0.950714306409916,
                            0.731993941811405,
                            0.598658484197037,
                            0.156018640442437,
                            0.155994520336203,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.058083612168199,
                            0.866176145774935,
                            0.601115011743209,
                            0.708072577796045,
                            0.020584494295802,
                            0.969909852161994,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.832442640800422,
                            0.212339110678276,
                            0.181824967207101,
                            0.183404509853434,
                            0.304242242959538,
                            0.524756431632238,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.431945018642116,
                            0.291229140198042,
                            0.611852894722379,
                            0.139493860652042,
                            0.292144648535218,
                            0.366361843293692,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.456069984217036,
                            0.785175961393014,
                            0.19967378215836,
                            0.514234438413612,
                            0.592414568862042,
                            0.046450412719998,
                        ]
                    ),
                ]
            ],
        ]
        if with_external_force
        else None
    )

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.TORQUE_DRIVEN,
            with_contact=with_contact,
            rigidbody_dynamics=rigidbody_dynamics,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
            external_forces=external_forces,
        ),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    np.random.seed(42)
    if with_external_force:
        np.random.rand(nlp.ns, 6)  # just not to change the values of the next random values

    # Prepare the dynamics
    if phase_dynamics == PhaseDynamics.SHARED_DURING_THE_PHASE and with_external_force:
        with pytest.raises(
            RuntimeError,
            match="Phase 0 has external_forces but the phase_dynamics is PhaseDynamics.SHARED_DURING_THE_PHASE.Please set phase_dynamics=PhaseDynamics.ONE_PER_NODE",
        ):
            ConfigureProblem.initialize(ocp, nlp)
        return
    else:
        ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))
    if rigidbody_dynamics == RigidBodyDynamics.ODE:
        if with_contact:
            contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
            if with_external_force:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.9695846, 0.9218742, 0.3886773, 0.5426961, -2.2030836, -0.3463042, 4.4577117, -3.5917074],
                )
                np.testing.assert_almost_equal(contact_out[:, 0], [-14.3821076, 126.2899884, 4.1631847])

            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.6118529, 0.785176, 0.6075449, 0.8083973, -0.3214905, -0.1912131, 0.6507164, -0.2359716],
                )
                np.testing.assert_almost_equal(contact_out[:, 0], [-2.444071, 128.8816865, 2.7245124])

        else:
            if with_external_force:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.9695846, 0.9218742, 0.3886773, 0.5426961, -1.090359, -10.1284375, 4.8896337, 13.5217526],
                )
            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [
                        0.61185289,
                        0.78517596,
                        0.60754485,
                        0.80839735,
                        -0.30241366,
                        -10.38503791,
                        1.60445173,
                        35.80238642,
                    ],
                )
    elif rigidbody_dynamics == RigidBodyDynamics.DAE_FORWARD_DYNAMICS:
        if with_contact:
            contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
            if with_external_force:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.9695846, 0.9218742, 0.3886773, 0.5426961, 0.1195942, 0.4937956, 0.0314292, 0.2492922],
                )
                np.testing.assert_almost_equal(contact_out[:, 0], [-14.3821076, 126.2899884, 4.1631847])
            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0], [0.6118529, 0.785176, 0.6075449, 0.8083973, 0.3886773, 0.5426961, 0.7722448, 0.7290072]
                )
                np.testing.assert_almost_equal(contact_out[:, 0], [-2.444071, 128.8816865, 2.7245124])

        else:
            if with_external_force:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.9695846, 0.9218742, 0.3886773, 0.5426961, 0.1195942, 0.4937956, 0.0314292, 0.2492922],
                )
            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.6118529, 0.785176, 0.6075449, 0.8083973, 0.3886773, 0.5426961, 0.7722448, 0.7290072],
                )
    elif rigidbody_dynamics == RigidBodyDynamics.DAE_INVERSE_DYNAMICS:
        if with_contact:
            contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
            if with_external_force:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.9695846, 0.9218742, 0.3886773, 0.5426961, 0.1195942, 0.4937956, 0.0314292, 0.2492922],
                )
                np.testing.assert_almost_equal(contact_out[:, 0], [-14.3821076, 126.2899884, 4.1631847])
            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0], [0.6118529, 0.785176, 0.6075449, 0.8083973, 0.3886773, 0.5426961, 0.7722448, 0.7290072]
                )
                np.testing.assert_almost_equal(contact_out[:, 0], [-2.444071, 128.8816865, 2.7245124])

        else:
            if with_external_force:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.9695846, 0.9218742, 0.3886773, 0.5426961, 0.1195942, 0.4937956, 0.0314292, 0.2492922],
                )
            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.6118529, 0.785176, 0.6075449, 0.8083973, 0.3886773, 0.5426961, 0.7722448, 0.7290072],
                )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_contact", [False, True])
def test_torque_driven_implicit(with_contact, cx, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)

    nlp.x_bounds = np.zeros((nlp.model.nb_q * 3, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q * 2, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT

    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.TORQUE_DRIVEN,
            with_contact=with_contact,
            rigidbody_dynamics=RigidBodyDynamics.DAE_INVERSE_DYNAMICS,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
        ),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    # Prepare the dynamics
    ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    np.random.seed(42)
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_contact:
        contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
        np.testing.assert_almost_equal(
            x_out[:, 0], [0.6118529, 0.785176, 0.6075449, 0.8083973, 0.3886773, 0.5426961, 0.7722448, 0.7290072]
        )

        np.testing.assert_almost_equal(contact_out[:, 0], [-2.444071, 128.8816865, 2.7245124])

    else:
        np.testing.assert_almost_equal(
            x_out[:, 0],
            [0.6118529, 0.785176, 0.6075449, 0.8083973, 0.3886773, 0.5426961, 0.7722448, 0.7290072],
        )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_contact", [False, True])
@pytest.mark.parametrize("implicit_contact", [False, True])
def test_torque_driven_soft_contacts_dynamics(with_contact, cx, implicit_contact, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)

    nlp.x_bounds = np.zeros((nlp.model.nb_q * (2 + 3), 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q * 2, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT

    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.TORQUE_DRIVEN,
            with_contact=with_contact,
            soft_contacts_dynamics=implicit_contact,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
        ),
        False,
    )

    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    # Prepare the dynamics
    ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    np.random.seed(42)
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_contact:
        contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
        np.testing.assert_almost_equal(
            x_out[:, 0], [0.6118529, 0.785176, 0.6075449, 0.8083973, -0.3214905, -0.1912131, 0.6507164, -0.2359716]
        )

        np.testing.assert_almost_equal(contact_out[:, 0], [-2.444071, 128.8816865, 2.7245124])

    else:
        np.testing.assert_almost_equal(
            x_out[:, 0],
            [0.6118529, 0.785176, 0.6075449, 0.8083973, -0.3024137, -10.3850379, 1.6044517, 35.8023864],
        )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_external_force", [False, True])
@pytest.mark.parametrize("with_contact", [False, True])
def test_torque_derivative_driven(with_contact, with_external_force, cx, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)
    nlp.x_bounds = np.zeros((nlp.model.nb_q * 3, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT

    external_forces = (
        [
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.3745401188473625,
                            0.9507143064099162,
                            0.7319939418114051,
                            0.5986584841970366,
                            0.15601864044243652,
                            0.15599452033620265,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.05808361216819946,
                            0.8661761457749352,
                            0.6011150117432088,
                            0.7080725777960455,
                            0.020584494295802447,
                            0.9699098521619943,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.8324426408004217,
                            0.21233911067827616,
                            0.18182496720710062,
                            0.18340450985343382,
                            0.3042422429595377,
                            0.5247564316322378,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.43194501864211576,
                            0.2912291401980419,
                            0.6118528947223795,
                            0.13949386065204183,
                            0.29214464853521815,
                            0.3663618432936917,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.45606998421703593,
                            0.7851759613930136,
                            0.19967378215835974,
                            0.5142344384136116,
                            0.5924145688620425,
                            0.046450412719997725,
                        ]
                    ),
                ]
            ],
        ]
        if with_external_force
        else None
    )

    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.TORQUE_DERIVATIVE_DRIVEN,
            with_contact=with_contact,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
            external_forces=external_forces,
        ),
        False,
    )

    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    np.random.seed(42)
    if with_external_force:
        np.random.rand(nlp.ns, 6)

    # Prepare the dynamics
    if phase_dynamics == PhaseDynamics.SHARED_DURING_THE_PHASE and with_external_force:
        with pytest.raises(
            RuntimeError,
            match="Phase 0 has external_forces but the phase_dynamics is PhaseDynamics.SHARED_DURING_THE_PHASE.Please set phase_dynamics=PhaseDynamics.ONE_PER_NODE",
        ):
            ConfigureProblem.initialize(ocp, nlp)
        return
    else:
        ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_contact:
        contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
        if with_external_force:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [
                    0.9695846,
                    0.9218742,
                    0.3886773,
                    0.5426961,
                    -2.2030836,
                    -0.3463042,
                    4.4577117,
                    -3.5917074,
                    0.1195942,
                    0.4937956,
                    0.0314292,
                    0.2492922,
                ],
            )
            np.testing.assert_almost_equal(contact_out[:, 0], [-14.3821076, 126.2899884, 4.1631847])
        else:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [
                    0.61185289,
                    0.78517596,
                    0.60754485,
                    0.80839735,
                    -0.32149054,
                    -0.19121314,
                    0.65071636,
                    -0.23597164,
                    0.38867729,
                    0.54269608,
                    0.77224477,
                    0.72900717,
                ],
            )
            np.testing.assert_almost_equal(contact_out[:, 0], [-2.444071, 128.8816865, 2.7245124])

    else:
        if with_external_force:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [
                    0.9695846,
                    0.9218742,
                    0.3886773,
                    0.5426961,
                    -1.090359,
                    -10.1284375,
                    4.8896337,
                    13.5217526,
                    0.1195942,
                    0.4937956,
                    0.0314292,
                    0.2492922,
                ],
            )
        else:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [
                    0.61185289,
                    0.78517596,
                    0.60754485,
                    0.80839735,
                    -0.30241366,
                    -10.38503791,
                    1.60445173,
                    35.80238642,
                    0.38867729,
                    0.54269608,
                    0.77224477,
                    0.72900717,
                ],
            )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_contact", [False, True])
def test_torque_derivative_driven_implicit(with_contact, cx, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)
    nlp.phase_idx = 0
    nlp.x_bounds = np.zeros((nlp.model.nb_q * 4, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q, 2))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.TORQUE_DERIVATIVE_DRIVEN,
            with_contact=with_contact,
            rigidbody_dynamics=RigidBodyDynamics.DAE_INVERSE_DYNAMICS,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
        ),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    # Prepare the dynamics
    ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    np.random.seed(42)
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_contact:
        contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
        np.testing.assert_almost_equal(
            x_out[:, 0],
            [
                0.6118529,
                0.785176,
                0.6075449,
                0.8083973,
                0.3886773,
                0.5426961,
                0.7722448,
                0.7290072,
                0.8631034,
                0.3251833,
                0.1195942,
                0.4937956,
                0.0314292,
                0.2492922,
                0.2897515,
                0.8714606,
            ],
        )
        np.testing.assert_almost_equal(contact_out[:, 0], [-2.444071, 128.8816865, 2.7245124])
    else:
        np.testing.assert_almost_equal(
            x_out[:, 0],
            [
                0.6118529,
                0.785176,
                0.6075449,
                0.8083973,
                0.3886773,
                0.5426961,
                0.7722448,
                0.7290072,
                0.8631034,
                0.3251833,
                0.1195942,
                0.4937956,
                0.0314292,
                0.2492922,
                0.2897515,
                0.8714606,
            ],
        )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_contact", [False, True])
@pytest.mark.parametrize("implicit_contact", [False, True])
def test_torque_derivative_driven_soft_contacts_dynamics(with_contact, cx, implicit_contact, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)

    nlp.x_bounds = np.zeros((nlp.model.nb_q * (2 + 3), 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q * 4, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.TORQUE_DERIVATIVE_DRIVEN,
            with_contact=with_contact,
            soft_contacts_dynamics=implicit_contact,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
        ),
        False,
    )

    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    # Prepare the dynamics
    ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    np.random.seed(42)
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_contact:
        contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
        np.testing.assert_almost_equal(
            x_out[:, 0],
            [
                0.6118529,
                0.785176,
                0.6075449,
                0.8083973,
                -0.3214905,
                -0.1912131,
                0.6507164,
                -0.2359716,
                0.3886773,
                0.5426961,
                0.7722448,
                0.7290072,
            ],
        )
        np.testing.assert_almost_equal(contact_out[:, 0], [-2.444071, 128.8816865, 2.7245124])

    else:
        np.testing.assert_almost_equal(
            x_out[:, 0],
            [
                0.6118529,
                0.785176,
                0.6075449,
                0.8083973,
                -0.3024137,
                -10.3850379,
                1.6044517,
                35.8023864,
                0.3886773,
                0.5426961,
                0.7722448,
                0.7290072,
            ],
        )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize(
    "dynamics",
    [DynamicsFcn.TORQUE_ACTIVATIONS_DRIVEN, DynamicsFcn.MUSCLE_DRIVEN],
)
def test_soft_contacts_dynamics_errors(dynamics, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = MX

    nlp.u_bounds = np.zeros((nlp.model.nb_q * 4, 1))
    nlp.u_scaling = VariableScalingList()

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(dynamics, soft_contacts_dynamics=True, expand_dynamics=True, phase_dynamics=phase_dynamics),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    # Prepare the dynamics
    with pytest.raises(
        TypeError,
        match=re.escape(f"{dynamics.name.lower()}() got an unexpected keyword argument " "'soft_contacts_dynamics'"),
    ):
        ConfigureProblem.initialize(ocp, nlp)


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("dynamics", [DynamicsFcn.TORQUE_ACTIVATIONS_DRIVEN])
def test_implicit_dynamics_errors(dynamics, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = MX

    nlp.u_bounds = np.zeros((nlp.model.nb_q * 4, 1))
    nlp.u_scaling = VariableScalingList()

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            dynamics,
            rigidbody_dynamics=RigidBodyDynamics.DAE_INVERSE_DYNAMICS,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
        ),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    # Prepare the dynamics
    with pytest.raises(
        TypeError,
        match=re.escape(f"{dynamics.name.lower()}() got an unexpected keyword argument " "'rigidbody_dynamics'"),
    ):
        ConfigureProblem.initialize(ocp, nlp)


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_external_force", [False, True])
@pytest.mark.parametrize("with_contact", [False, True])
def test_torque_activation_driven(with_contact, with_external_force, cx, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)

    nlp.x_bounds = np.zeros((nlp.model.nb_q * 2, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    external_forces = (
        [
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.3745401188473625,
                            0.9507143064099162,
                            0.7319939418114051,
                            0.5986584841970366,
                            0.15601864044243652,
                            0.15599452033620265,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.05808361216819946,
                            0.8661761457749352,
                            0.6011150117432088,
                            0.7080725777960455,
                            0.020584494295802447,
                            0.9699098521619943,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.8324426408004217,
                            0.21233911067827616,
                            0.18182496720710062,
                            0.18340450985343382,
                            0.3042422429595377,
                            0.5247564316322378,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.43194501864211576,
                            0.2912291401980419,
                            0.6118528947223795,
                            0.13949386065204183,
                            0.29214464853521815,
                            0.3663618432936917,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.45606998421703593,
                            0.7851759613930136,
                            0.19967378215835974,
                            0.5142344384136116,
                            0.5924145688620425,
                            0.046450412719997725,
                        ]
                    ),
                ]
            ],
        ]
        if with_external_force
        else None
    )

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.TORQUE_ACTIVATIONS_DRIVEN,
            with_contact=with_contact,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
            external_forces=external_forces,
        ),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    np.random.seed(42)
    if with_external_force:
        np.random.rand(nlp.ns, 6)

    # Prepare the dynamics
    if phase_dynamics == PhaseDynamics.SHARED_DURING_THE_PHASE and with_external_force:
        with pytest.raises(
            RuntimeError,
            match="Phase 0 has external_forces but the phase_dynamics is PhaseDynamics.SHARED_DURING_THE_PHASE.Please set phase_dynamics=PhaseDynamics.ONE_PER_NODE",
        ):
            ConfigureProblem.initialize(ocp, nlp)
        return
    else:
        ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_contact:
        contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
        if with_external_force:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [0.96958, 0.92187, 0.38868, 0.5427, -8.22427, -1.08479, 16.59032, -15.72432],
                decimal=5,
            )
            np.testing.assert_almost_equal(contact_out[:, 0], [-126.9614581, 179.6585112, -125.8079563])
        else:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [0.61185289, 0.78517596, 0.60754485, 0.80839735, 0.78455384, -0.16844256, -1.56184114, 1.97658587],
                decimal=5,
            )
            np.testing.assert_almost_equal(contact_out[:, 0], [-7.88958997, 329.70828173, -263.55516549])

    else:
        if with_external_force:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [
                    9.69584628e-01,
                    9.21874235e-01,
                    3.88677290e-01,
                    5.42696083e-01,
                    -6.35312971e01,
                    -3.16877667e01,
                    3.09696095e02,
                    1.36002265e03,
                ],
                decimal=5,
            )
        else:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [
                    6.11852895e-01,
                    7.85175961e-01,
                    6.07544852e-01,
                    8.08397348e-01,
                    -2.38262975e01,
                    -5.82033454e01,
                    1.27439020e02,
                    3.66531163e03,
                ],
                decimal=5,
            )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_residual_torque", [False, True])
@pytest.mark.parametrize("with_external_force", [False, True])
@pytest.mark.parametrize("with_passive_torque", [False, True])
def test_torque_activation_driven_with_residual_torque(
    with_residual_torque, with_external_force, with_passive_torque, cx, phase_dynamics
):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/torque_driven_ocp/models/2segments_2dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)
    nlp.x_bounds = np.zeros((nlp.model.nb_q * 2, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    external_forces = (
        [
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.3745401188473625,
                            0.9507143064099162,
                            0.7319939418114051,
                            0.5986584841970366,
                            0.15601864044243652,
                            0.15599452033620265,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.05808361216819946,
                            0.8661761457749352,
                            0.6011150117432088,
                            0.7080725777960455,
                            0.020584494295802447,
                            0.9699098521619943,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.8324426408004217,
                            0.21233911067827616,
                            0.18182496720710062,
                            0.18340450985343382,
                            0.3042422429595377,
                            0.5247564316322378,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.43194501864211576,
                            0.2912291401980419,
                            0.6118528947223795,
                            0.13949386065204183,
                            0.29214464853521815,
                            0.3663618432936917,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.45606998421703593,
                            0.7851759613930136,
                            0.19967378215835974,
                            0.5142344384136116,
                            0.5924145688620425,
                            0.046450412719997725,
                        ]
                    ),
                ]
            ],
        ]
        if with_external_force
        else None
    )

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.TORQUE_ACTIVATIONS_DRIVEN,
            with_residual_torque=with_residual_torque,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
            external_forces=external_forces,
        ),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    np.random.seed(42)
    if with_external_force:
        np.random.rand(nlp.ns, 6)

    # Prepare the dynamics
    if phase_dynamics == PhaseDynamics.SHARED_DURING_THE_PHASE and with_external_force:
        with pytest.raises(
            RuntimeError,
            match="Phase 0 has external_forces but the phase_dynamics is PhaseDynamics.SHARED_DURING_THE_PHASE.Please set phase_dynamics=PhaseDynamics.ONE_PER_NODE",
        ):
            ConfigureProblem.initialize(ocp, nlp)
        return
    else:
        ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_residual_torque:
        if with_external_force:
            if with_passive_torque:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [1.22038235e-01, 6.62522284e-01, 1.52446740e02, 1.79223051e03],
                    decimal=5,
                )
            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [1.22038235e-01, 6.62522284e-01, 1.52446740e02, 1.79223051e03],
                    decimal=5,
                )
        else:
            if with_passive_torque:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.020584, 0.183405, 55.393940, 54.222523],
                    decimal=5,
                )
            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.020584, 0.183405, 55.393940, 54.222523],
                    decimal=5,
                )

    else:
        if with_external_force:
            if with_passive_torque:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [1.22038235e-01, 6.62522284e-01, 1.51341897e02, 1.77042854e03],
                    decimal=5,
                )
            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [1.22038235e-01, 6.62522284e-01, 1.51341897e02, 1.77042854e03],
                    decimal=5,
                )
        else:
            if with_passive_torque:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.020584, 0.183405, 55.204243, 24.411235],
                    decimal=5,
                )
            else:
                np.testing.assert_almost_equal(
                    x_out[:, 0],
                    [0.020584, 0.183405, 55.204243, 24.411235],
                    decimal=5,
                )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_external_force", [False, True])
@pytest.mark.parametrize("with_contact", [False, True])
def test_torque_driven(with_contact, with_external_force, cx, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)

    nlp.x_bounds = np.zeros((nlp.model.nb_q * 3, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    external_forces = (
        [
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.374540118847362,
                            0.950714306409916,
                            0.731993941811405,
                            0.598658484197037,
                            0.156018640442437,
                            0.155994520336203,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.058083612168199,
                            0.866176145774935,
                            0.601115011743209,
                            0.708072577796045,
                            0.020584494295802,
                            0.969909852161994,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.832442640800422,
                            0.212339110678276,
                            0.181824967207101,
                            0.183404509853434,
                            0.304242242959538,
                            0.524756431632238,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.431945018642116,
                            0.291229140198042,
                            0.611852894722379,
                            0.139493860652042,
                            0.292144648535218,
                            0.366361843293692,
                        ]
                    ),
                ]
            ],
            [
                [
                    "Seg0",
                    np.array(
                        [
                            0.456069984217036,
                            0.785175961393014,
                            0.19967378215836,
                            0.514234438413612,
                            0.592414568862042,
                            0.046450412719998,
                        ]
                    ),
                ]
            ],
        ]
        if with_external_force
        else None
    )

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.TORQUE_DRIVEN_FREE_FLOATING_BASE,
            with_contact=with_contact,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
            external_forces=external_forces,
        ),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    np.random.seed(42)
    if with_external_force:
        np.random.rand(nlp.ns, 6)  # just not to change the values of the next random values

    # Prepare the dynamics
    if phase_dynamics == PhaseDynamics.SHARED_DURING_THE_PHASE and with_external_force:
        with pytest.raises(
            RuntimeError,
            match="Phase 0 has external_forces but the phase_dynamics is PhaseDynamics.SHARED_DURING_THE_PHASE.Please set phase_dynamics=PhaseDynamics.ONE_PER_NODE",
        ):
            ConfigureProblem.initialize(ocp, nlp)
        return
    else:
        ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2, 1)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_contact:
        contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
        if with_external_force:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [0.96958463, 0.92187424, 0.38867729, 0.54269608, -1.71642952, -0.28661718, 3.47711038, -2.61110605],
            )
            np.testing.assert_almost_equal(contact_out[:, 0], [-12.59366904, 128.27098855, 2.35829492])

        else:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [0.61185289, 0.78517596, 0.60754485, 0.80839735, -0.26487805, -0.19004763, 0.53746739, -0.12272266],
            )
            np.testing.assert_almost_equal(contact_out[:, 0], [-2.30360748, 127.09143179, 5.05814294])

    else:
        if with_external_force:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [0.96958463, 0.92187424, 0.38867729, 0.54269608, -0.21234549, -10.23941443, 2.07066831, 31.68033189],
            )
        else:
            np.testing.assert_almost_equal(
                x_out[:, 0],
                [0.61185289, 0.78517596, 0.60754485, 0.80839735, 0.04791036, -9.96778948, -0.01986505, 4.39786051],
            )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("with_external_force", [False, True])
@pytest.mark.parametrize("with_contact", [False, True])
@pytest.mark.parametrize("with_residual_torque", [False, True])
@pytest.mark.parametrize("with_excitations", [False, True])
@pytest.mark.parametrize("rigidbody_dynamics", [RigidBodyDynamics.ODE, RigidBodyDynamics.DAE_INVERSE_DYNAMICS])
def test_muscle_driven(
    with_excitations, with_contact, with_residual_torque, with_external_force, rigidbody_dynamics, cx, phase_dynamics
):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(TestUtils.bioptim_folder() + "/examples/muscle_driven_ocp/models/arm26_with_contact.bioMod")
    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(cx)

    nlp.x_bounds = np.zeros((nlp.model.nb_q * 2 + nlp.model.nb_muscles, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_muscles, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()
    nlp.phase_idx = 0

    external_forces = (
        [
            [
                [
                    "r_ulna_radius_hand_rotation1",
                    np.array(
                        [
                            0.3745401188473625,
                            0.9507143064099162,
                            0.7319939418114051,
                            0.5986584841970366,
                            0.15601864044243652,
                            0.15599452033620265,
                        ]
                    ),
                ]
            ],
            [
                [
                    "r_ulna_radius_hand_rotation1",
                    np.array(
                        [
                            0.05808361216819946,
                            0.8661761457749352,
                            0.6011150117432088,
                            0.7080725777960455,
                            0.020584494295802447,
                            0.9699098521619943,
                        ]
                    ),
                ]
            ],
            [
                [
                    "r_ulna_radius_hand_rotation1",
                    np.array(
                        [
                            0.8324426408004217,
                            0.21233911067827616,
                            0.18182496720710062,
                            0.18340450985343382,
                            0.3042422429595377,
                            0.5247564316322378,
                        ]
                    ),
                ]
            ],
            [
                [
                    "r_ulna_radius_hand_rotation1",
                    np.array(
                        [
                            0.43194501864211576,
                            0.2912291401980419,
                            0.6118528947223795,
                            0.13949386065204183,
                            0.29214464853521815,
                            0.3663618432936917,
                        ]
                    ),
                ]
            ],
            [
                [
                    "r_ulna_radius_hand_rotation1",
                    np.array(
                        [
                            0.45606998421703593,
                            0.7851759613930136,
                            0.19967378215835974,
                            0.5142344384136116,
                            0.5924145688620425,
                            0.046450412719997725,
                        ]
                    ),
                ]
            ],
        ]
        if with_external_force
        else None
    )

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.MUSCLE_DRIVEN,
            with_residual_torque=with_residual_torque,
            with_excitations=with_excitations,
            with_contact=with_contact,
            rigidbody_dynamics=rigidbody_dynamics,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
            external_forces=external_forces,
        ),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    np.random.seed(42)
    if with_external_force:
        np.random.rand(nlp.ns, 6)  # just to make sure the next random is the same as before

    # Prepare the dynamics
    if rigidbody_dynamics == RigidBodyDynamics.DAE_INVERSE_DYNAMICS:
        pass
    if phase_dynamics == PhaseDynamics.SHARED_DURING_THE_PHASE and with_external_force:
        with pytest.raises(
            RuntimeError,
            match="Phase 0 has external_forces but the phase_dynamics is PhaseDynamics.SHARED_DURING_THE_PHASE.Please set phase_dynamics=PhaseDynamics.ONE_PER_NODE",
        ):
            ConfigureProblem.initialize(ocp, nlp)
        return
    else:
        ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_contact:  # Warning this test is a bit bogus, there since the model does not have contacts
        if rigidbody_dynamics == RigidBodyDynamics.DAE_INVERSE_DYNAMICS:
            if with_residual_torque:
                if with_excitations:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.6625223,
                                0.9695846,
                                0.9218742,
                                0.3232029,
                                0.9624473,
                                0.0368869,
                                -3.773906,
                                -8.3095101,
                                5.9827416,
                                4.9220243,
                                -19.5615453,
                                9.336912,
                            ],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.183405,
                                0.611853,
                                0.785176,
                                0.249292,
                                0.289751,
                                0.871461,
                                8.606308,
                                3.194336,
                                29.740561,
                                -20.275423,
                                -23.246778,
                                -41.913501,
                            ],
                            decimal=6,
                        )
                else:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.662522, 0.969585, 0.921874, 0.249292, 0.289751, 0.871461],
                            decimal=6,
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.183405, 0.611853, 0.785176, 0.729007, 0.863103, 0.325183],
                            decimal=6,
                        )

            else:
                if with_excitations:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.6625223,
                                0.9695846,
                                0.9218742,
                                0.8074402,
                                0.4271078,
                                0.417411,
                                -7.2855306,
                                -1.6064349,
                                -30.7136058,
                                -19.1107728,
                                -25.7242266,
                                55.3038169,
                            ],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                1.83404510e-01,
                                6.11852895e-01,
                                7.85175961e-01,
                                1.19594246e-01,
                                4.93795596e-01,
                                3.14291857e-02,
                                -7.72228930e00,
                                -1.13759732e01,
                                9.51906209e01,
                                4.45077128e00,
                                -5.20261014e00,
                                -2.80864106e01,
                            ],
                            decimal=6,
                        )
                else:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.6625223, 0.9695846, 0.9218742, 0.1195942, 0.4937956, 0.0314292],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.183405, 0.611853, 0.785176, 0.388677, 0.542696, 0.772245],
                            decimal=6,
                        )
        else:
            if with_residual_torque:
                if with_excitations:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.6625223,
                                0.9695846,
                                0.9218742,
                                0.2123157,
                                -29.9955403,
                                -37.8135747,
                                -3.773906,
                                -8.3095101,
                                5.9827416,
                                4.9220243,
                                -19.5615453,
                                9.336912,
                            ],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                1.83404510e-01,
                                6.11852895e-01,
                                7.85175961e-01,
                                -3.94658983e00,
                                1.23227027e02,
                                -4.38936797e02,
                                8.60630831e00,
                                3.19433638e00,
                                2.97405608e01,
                                -2.02754226e01,
                                -2.32467778e01,
                                -4.19135012e01,
                            ],
                            decimal=6,
                        )
                else:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.662522, 0.969585, 0.921874, 1.151072, -56.094393, 49.109365],
                            decimal=6,
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.183405, 0.611853, 0.785176, -0.867138, 22.511947, -153.294775],
                            decimal=6,
                        )

            else:
                if with_excitations:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.6625223,
                                0.9695846,
                                0.9218742,
                                0.2684853,
                                -33.7252751,
                                -30.3079326,
                                -7.2855306,
                                -1.6064349,
                                -30.7136058,
                                -19.1107728,
                                -25.7242266,
                                55.3038169,
                            ],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                1.83404510e-01,
                                6.11852895e-01,
                                7.85175961e-01,
                                -4.37708456e00,
                                1.33221135e02,
                                -4.71307550e02,
                                -7.72228930e00,
                                -1.13759732e01,
                                9.51906209e01,
                                4.45077128e00,
                                -5.20261014e00,
                                -2.80864106e01,
                            ],
                            decimal=6,
                        )
                else:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.6625223, 0.9695846, 0.9218742, 0.2684853, -33.7252751, -30.3079326],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                1.83404510e-01,
                                6.11852895e-01,
                                7.85175961e-01,
                                -4.37708456e00,
                                1.33221135e02,
                                -4.71307550e02,
                            ],
                            decimal=6,
                        )
    else:
        if rigidbody_dynamics == RigidBodyDynamics.DAE_INVERSE_DYNAMICS:
            if with_residual_torque:
                if with_excitations:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.6625223,
                                0.9695846,
                                0.9218742,
                                0.3232029,
                                0.9624473,
                                0.0368869,
                                -3.773906,
                                -8.3095101,
                                5.9827416,
                                4.9220243,
                                -19.5615453,
                                9.336912,
                            ],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.183405,
                                0.611853,
                                0.785176,
                                0.249292,
                                0.289751,
                                0.871461,
                                8.606308,
                                3.194336,
                                29.740561,
                                -20.275423,
                                -23.246778,
                                -41.913501,
                            ],
                            decimal=6,
                        )
                else:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.662522, 0.969585, 0.921874, 0.249292, 0.289751, 0.871461],
                            decimal=6,
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.183405, 0.611853, 0.785176, 0.729007, 0.863103, 0.325183],
                            decimal=6,
                        )

            else:
                if with_excitations:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.6625223,
                                0.9695846,
                                0.9218742,
                                0.8074402,
                                0.4271078,
                                0.417411,
                                -7.2855306,
                                -1.6064349,
                                -30.7136058,
                                -19.1107728,
                                -25.7242266,
                                55.3038169,
                            ],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                1.83404510e-01,
                                6.11852895e-01,
                                7.85175961e-01,
                                1.19594246e-01,
                                4.93795596e-01,
                                3.14291857e-02,
                                -7.72228930e00,
                                -1.13759732e01,
                                9.51906209e01,
                                4.45077128e00,
                                -5.20261014e00,
                                -2.80864106e01,
                            ],
                            decimal=6,
                        )
                else:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.6625223, 0.9695846, 0.9218742, 0.1195942, 0.4937956, 0.0314292],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.183405, 0.611853, 0.785176, 0.388677, 0.542696, 0.772245],
                            decimal=6,
                        )
        else:
            if with_residual_torque:
                if with_excitations:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.6625223,
                                0.9695846,
                                0.9218742,
                                0.2123157,
                                -29.9955403,
                                -37.8135747,
                                -3.773906,
                                -8.3095101,
                                5.9827416,
                                4.9220243,
                                -19.5615453,
                                9.336912,
                            ],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                1.83404510e-01,
                                6.11852895e-01,
                                7.85175961e-01,
                                -3.94658983e00,
                                1.23227027e02,
                                -4.38936797e02,
                                8.60630831e00,
                                3.19433638e00,
                                2.97405608e01,
                                -2.02754226e01,
                                -2.32467778e01,
                                -4.19135012e01,
                            ],
                            decimal=6,
                        )
                else:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.662522, 0.969585, 0.921874, 1.151072, -56.094393, 49.109365],
                            decimal=6,
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.18340451, 0.61185289, 0.78517596, -0.8671376, 22.51194682, -153.29477496],
                            decimal=6,
                        )

            else:
                if with_excitations:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                0.6625223,
                                0.9695846,
                                0.9218742,
                                0.2684853,
                                -33.7252751,
                                -30.3079326,
                                -7.2855306,
                                -1.6064349,
                                -30.7136058,
                                -19.1107728,
                                -25.7242266,
                                55.3038169,
                            ],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                1.83404510e-01,
                                6.11852895e-01,
                                7.85175961e-01,
                                -4.37708456e00,
                                1.33221135e02,
                                -4.71307550e02,
                                -7.72228930e00,
                                -1.13759732e01,
                                9.51906209e01,
                                4.45077128e00,
                                -5.20261014e00,
                                -2.80864106e01,
                            ],
                            decimal=6,
                        )
                else:
                    if with_external_force:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [0.6625223, 0.9695846, 0.9218742, 0.2684853, -33.7252751, -30.3079326],
                        )
                    else:
                        np.testing.assert_almost_equal(
                            x_out[:, 0],
                            [
                                1.83404510e-01,
                                6.11852895e-01,
                                7.85175961e-01,
                                -4.37708456e00,
                                1.33221135e02,
                                -4.71307550e02,
                            ],
                            decimal=6,
                        )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("cx", [MX, SX])
@pytest.mark.parametrize("rigid_body_dynamics", RigidBodyDynamics)
def test_joints_acceleration_driven(cx, rigid_body_dynamics, phase_dynamics):
    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(TestUtils.bioptim_folder() + "/examples/getting_started/models/double_pendulum.bioMod")

    nlp.ns = 5
    nlp.cx = cx
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(nlp.cx)

    nlp.x_bounds = np.zeros((nlp.model.nb_q * 3, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT

    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            DynamicsFcn.JOINTS_ACCELERATION_DRIVEN,
            rigidbody_dynamics=rigid_body_dynamics,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
        ),
        False,
    )
    np.random.seed(42)
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    # Prepare the dynamics
    if rigid_body_dynamics != RigidBodyDynamics.ODE:
        with pytest.raises(NotImplementedError, match=re.escape("Implicit dynamics not implemented yet.")):
            ConfigureProblem.initialize(ocp, nlp)
    else:
        ConfigureProblem.initialize(ocp, nlp)

        # Test the results
        states = np.random.rand(nlp.states.shape, nlp.ns)
        controls = np.random.rand(nlp.controls.shape, nlp.ns)
        params = np.random.rand(nlp.parameters.shape, nlp.ns)
        algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
        time = np.random.rand(2)
        x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

        # obtained using Ipuch reference implementation. [https://github.com/Ipuch/OnDynamicsForSomersaults]
        np.testing.assert_almost_equal(x_out[:, 0], [0.02058449, 0.18340451, -2.95556261, 0.61185289])


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize("with_contact", [False, True])
def test_custom_dynamics(with_contact, phase_dynamics):
    def custom_dynamic(
        time, states, controls, parameters, algebraic_states, nlp, with_contact=False
    ) -> DynamicsEvaluation:
        q = DynamicsFunctions.get(nlp.states["q"], states)
        qdot = DynamicsFunctions.get(nlp.states["qdot"], states)
        tau = DynamicsFunctions.get(nlp.controls["tau"], controls)

        dq = DynamicsFunctions.compute_qdot(nlp, q, qdot)
        ddq = DynamicsFunctions.forward_dynamics(nlp, q, qdot, tau, with_contact)

        return DynamicsEvaluation(dxdt=vertcat(dq, ddq), defects=None)

    def configure(ocp, nlp, with_contact=None):
        ConfigureProblem.configure_q(ocp, nlp, True, False)
        ConfigureProblem.configure_qdot(ocp, nlp, True, False)
        ConfigureProblem.configure_tau(ocp, nlp, False, True)
        ConfigureProblem.configure_dynamics_function(ocp, nlp, custom_dynamic, with_contact=with_contact)

        if with_contact:
            ConfigureProblem.configure_contact_function(ocp, nlp, DynamicsFunctions.forces_from_torque_driven)

    # Prepare the program
    nlp = NonLinearProgram(phase_dynamics=phase_dynamics)
    nlp.model = BiorbdModel(
        TestUtils.bioptim_folder() + "/examples/getting_started/models/2segments_4dof_2contacts.bioMod"
    )
    nlp.ns = 5
    nlp.cx = MX
    nlp.time_mx = MX.sym("time", 1, 1)
    nlp.dt_mx = MX.sym("dt", 1, 1)
    nlp.initialize(nlp.cx)
    nlp.x_bounds = np.zeros((nlp.model.nb_q * 3, 1))
    nlp.u_bounds = np.zeros((nlp.model.nb_q, 1))
    nlp.x_scaling = VariableScalingList()
    nlp.xdot_scaling = VariableScalingList()
    nlp.u_scaling = VariableScalingList()
    nlp.s_scaling = VariableScalingList()

    ocp = OptimalControlProgram(nlp)
    nlp.control_type = ControlType.CONSTANT
    NonLinearProgram.add(
        ocp,
        "dynamics_type",
        Dynamics(
            configure,
            dynamic_function=custom_dynamic,
            with_contact=with_contact,
            expand_dynamics=True,
            phase_dynamics=phase_dynamics,
        ),
        False,
    )
    phase_index = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "phase_idx", phase_index, False)
    use_states_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_states_dot_from_phase_idx = [i for i in range(ocp.n_phases)]
    use_controls_from_phase_idx = [i for i in range(ocp.n_phases)]
    NonLinearProgram.add(ocp, "use_states_from_phase_idx", use_states_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_states_dot_from_phase_idx", use_states_dot_from_phase_idx, False)
    NonLinearProgram.add(ocp, "use_controls_from_phase_idx", use_controls_from_phase_idx, False)

    np.random.seed(42)

    # Prepare the dynamics
    ConfigureProblem.initialize(ocp, nlp)

    # Test the results
    states = np.random.rand(nlp.states.shape, nlp.ns)
    controls = np.random.rand(nlp.controls.shape, nlp.ns)
    params = np.random.rand(nlp.parameters.shape, nlp.ns)
    algebraic_states = np.random.rand(nlp.algebraic_states.shape, nlp.ns)
    time = np.random.rand(2)
    x_out = np.array(nlp.dynamics_func[0](time, states, controls, params, algebraic_states))

    if with_contact:
        contact_out = np.array(nlp.contact_forces_func(time, states, controls, params, algebraic_states))
        np.testing.assert_almost_equal(
            x_out[:, 0], [0.6118529, 0.785176, 0.6075449, 0.8083973, -0.3214905, -0.1912131, 0.6507164, -0.2359716]
        )
        np.testing.assert_almost_equal(contact_out[:, 0], [-2.444071, 128.8816865, 2.7245124])

    else:
        np.testing.assert_almost_equal(
            x_out[:, 0],
            [0.61185289, 0.78517596, 0.60754485, 0.80839735, -0.30241366, -10.38503791, 1.60445173, 35.80238642],
        )


@pytest.mark.parametrize("phase_dynamics", [PhaseDynamics.SHARED_DURING_THE_PHASE, PhaseDynamics.ONE_PER_NODE])
@pytest.mark.parametrize(
    "dynamics_fcn",
    [
        DynamicsFcn.TORQUE_DRIVEN,
        DynamicsFcn.MUSCLE_DRIVEN,
        DynamicsFcn.TORQUE_DERIVATIVE_DRIVEN,
        DynamicsFcn.TORQUE_ACTIVATIONS_DRIVEN,
    ],
)
def test_with_contact_error(dynamics_fcn, phase_dynamics):
    from bioptim.examples.getting_started import pendulum as ocp_module
    from bioptim import BoundsList, ObjectiveList, OdeSolver, OptimalControlProgram

    bioptim_folder = os.path.dirname(ocp_module.__file__)

    bio_model = BiorbdModel(bioptim_folder + "/models/pendulum.bioMod")

    # Add objective functions
    objective_functions = ObjectiveList()

    # Dynamics
    dynamics = Dynamics(dynamics_fcn, with_contact=True, expand_dynamics=True, phase_dynamics=phase_dynamics)

    # Path constraint
    x_bounds = BoundsList()
    x_bounds["q"] = bio_model.bounds_from_ranges("q")
    x_bounds["qdot"] = bio_model.bounds_from_ranges("qdot")

    # Define control path constraint
    n_tau = bio_model.nb_tau
    u_bounds = BoundsList()
    u_bounds["tau"] = [100] * n_tau, [100] * n_tau
    u_bounds["tau"][1, :] = 0  # Prevent the model from actively rotate

    with pytest.raises(ValueError, match="No contact defined in the .bioMod of phase 0, set with_contact to False"):
        OptimalControlProgram(
            bio_model=bio_model,
            dynamics=dynamics,
            n_shooting=5,
            phase_time=1,
            x_bounds=x_bounds,
            u_bounds=u_bounds,
            objective_functions=objective_functions,
            ode_solver=OdeSolver.RK4(),
        )
