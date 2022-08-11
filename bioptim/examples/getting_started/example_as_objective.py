"""
TODO: General cleaning
An optimal control program consisting in a pendulum starting downward and ending upward while requiring
the minimum of generalized forces. The solver is only allowed to move the pendulum sideways.

There is a catch however: there are regions in which the weight of the pendulum cannot go.
The problem is solved in two passes. In the first pass, continuity is an objective rather then a constraint.
The goal of the first pass is to find quickly a potential initial solution. This initial solution is then given
to the second pass in which continuity is a constraint to find the optimal solution.

During the optimization process, the graphs are updated real-time. Finally, once it finished optimizing, it animates
the model using the optimal solution.
"""

from casadi import sqrt
import numpy as np
import biorbd_casadi as biorbd
from bioptim import (
    OptimalControlProgram,
    Node,
    DynamicsFcn,
    Dynamics,
    Bounds,
    InterpolationType,
    QAndQDotBounds,
    NoisedInitialGuess,
    InitialGuess,
    ObjectiveFcn,
    ObjectiveList,
    ConstraintFcn,
    ConstraintList,
    OdeSolver,
    CostType,
    Solver,
    BiorbdInterface,
    Solution,
)


def out_of_sphere(all_pn, y, z):
    q = all_pn.nlp.states["q"].mx
    marker_q = all_pn.nlp.model.markers(q)[1].to_mx()

    distance = sqrt((y - marker_q[1]) ** 2 + (z - marker_q[2]) ** 2)

    return BiorbdInterface.mx_to_cx("out_of_sphere", distance, all_pn.nlp.states["q"])


def prepare_ocp_first_pass(
    biorbd_model_path: str,
    final_time: float,
    n_shooting: int,
    ode_solver: OdeSolver = OdeSolver.RK4(),
    use_sx: bool = True,
    n_threads: int = 1,
) -> OptimalControlProgram:
    """
    The initialization of an ocp

    Parameters
    ----------
    biorbd_model_path: str
        The path to the biorbd model
    final_time: float
        The time in second required to perform the task
    n_shooting: int
        The number of shooting points to define int the direct multiple shooting program
    ode_solver: OdeSolver = OdeSolver.RK4()
        Which type of OdeSolver to use
    use_sx: bool
        If the SX variable should be used instead of MX (can be extensive on RAM)
    n_threads: int
        The number of threads to use in the paralleling (1 = no parallel computing)

    Returns
    -------
    The OptimalControlProgram ready to be solved
    """

    biorbd_model = biorbd.Model(biorbd_model_path)

    # Add objective functions
    objective_functions = ObjectiveList()
    objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_CONTROL, weight=1, key="tau")
    objective_functions.add(ObjectiveFcn.Mayer.MINIMIZE_TIME, weight=100)

    # Dynamics
    dynamics = Dynamics(DynamicsFcn.TORQUE_DRIVEN)

    # Path constraint
    Ytrans = 0
    Xrot = 1
    START = 0
    END = -1

    x_bounds = QAndQDotBounds(biorbd_model)
    x_bounds[:, START] = 0
    x_bounds.min[Ytrans, END] = -0.01  # Give a little slack on the end position, otherwise to difficult
    x_bounds.max[Ytrans, END] = 0.01
    x_bounds[Xrot, END] = 3.14

    # Initial guess
    n_q = biorbd_model.nbQ()
    n_qdot = biorbd_model.nbQdot()
    x_init = NoisedInitialGuess([0] * (n_q + n_qdot), bounds=x_bounds, noise_magnitude=.001, n_shooting=n_shooting)

    # Define control path constraint
    n_tau = biorbd_model.nbGeneralizedTorque()
    tau_min, tau_max, tau_init = -300, 300, 0
    u_bounds = Bounds([tau_min] * n_tau, [tau_max] * n_tau)
    u_bounds[1, :] = 0  # Prevent the model from actively rotate

    u_init = NoisedInitialGuess([tau_init] * n_tau, bounds=u_bounds, noise_magnitude=.01, n_shooting=n_shooting-1)

    constraints = ConstraintList()
    # max_bound is practically at infinity
    constraints.add(out_of_sphere, y=0.05, z=0, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=0.75, z=.2, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=-0.45, z=0, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=1.4, z=.5, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=2, z=1.2, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=2, z=-0.7, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=2, z=-1.4, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=-2, z=0, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=-2, z=-0.7, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=-2, z=-1.4, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=-0.45, z=-1, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(ConstraintFcn.TIME_CONSTRAINT, max_bound=final_time)

    return OptimalControlProgram(
        biorbd_model,
        dynamics,
        n_shooting,
        final_time,
        x_init=x_init,
        u_init=u_init,
        x_bounds=x_bounds,
        u_bounds=u_bounds,
        objective_functions=objective_functions,
        constraints=constraints,
        ode_solver=ode_solver,
        use_sx=use_sx,
        n_threads=n_threads,
        # change the weight to observe the impact on the continuity of the solution
        # or comment to see how the constrained program would fare
        state_continuity_weight=1000000,
    )


def prepare_ocp_second_pass(
    biorbd_model_path: str,
    final_time: float,
    solution: Solution,
    ode_solver: OdeSolver = OdeSolver.RK4(),
    use_sx: bool = True,
    n_threads: int = 1,
) -> OptimalControlProgram:
    """
    The initialization of an ocp

    Parameters
    ----------
    biorbd_model_path: str
        The path to the biorbd model
    final_time: float
        The time in second required to perform the task
    n_shooting: int
        The number of shooting points to define int the direct multiple shooting program
    ode_solver: OdeSolver = OdeSolver.RK4()
        Which type of OdeSolver to use
    use_sx: bool
        If the SX variable should be used instead of MX (can be extensive on RAM)
    n_threads: int
        The number of threads to use in the paralleling (1 = no parallel computing)

    Returns
    -------
    The OptimalControlProgram ready to be solved
    """

    biorbd_model = biorbd.Model(biorbd_model_path)

    # Add objective functions
    objective_functions = ObjectiveList()
    objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_CONTROL, weight=1, key="tau")
    objective_functions.add(ObjectiveFcn.Mayer.MINIMIZE_TIME, weight=100)

    # Dynamics
    dynamics = Dynamics(DynamicsFcn.TORQUE_DRIVEN)

    # Path constraint
    Ytrans = 0
    Xrot = 1
    START = 0
    END = -1

    x_bounds = QAndQDotBounds(biorbd_model)
    x_bounds[:, START] = 0
    x_bounds.min[Ytrans, END] = -0.01  # Give a little slack on the end position, otherwise to difficult
    x_bounds.max[Ytrans, END] = 0.01
    x_bounds[Xrot, END] = 3.14

    # Initial guess
    x_init = np.vstack((solution.states["q"], solution.states["qdot"]))
    x_init = InitialGuess(x_init, interpolation=InterpolationType.EACH_FRAME)

    # Define control path constraint
    n_tau = biorbd_model.nbGeneralizedTorque()
    tau_min, tau_max, tau_init = -300, 300, 0
    u_bounds = Bounds([tau_min] * n_tau, [tau_max] * n_tau)
    u_bounds[1, :] = 0  # Prevent the model from actively rotate

    u_init = InitialGuess(solution.controls["tau"][:, :-1], interpolation=InterpolationType.EACH_FRAME)

    constraints = ConstraintList()
    # max_bound is practically at infinity
    constraints.add(out_of_sphere, y=0.05, z=0, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=0.75, z=.2, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=-0.45, z=0, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=1.4, z=.5, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=2, z=1.2, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=2, z=-0.7, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=2, z=-1.4, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    constraints.add(out_of_sphere, y=-2, z=0, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=-2, z=-0.7, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=-2, z=-1.4, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(out_of_sphere, y=-0.45, z=-1, min_bound=0.35, max_bound=np.inf, node=Node.ALL_SHOOTING)
    # constraints.add(ConstraintFcn.TIME_CONSTRAINT, max_bound=final_time)

    return OptimalControlProgram(
        biorbd_model,
        dynamics,
        solution.ns,
        final_time,
        x_init=x_init,
        u_init=u_init,
        x_bounds=x_bounds,
        u_bounds=u_bounds,
        objective_functions=objective_functions,
        constraints=constraints,
        ode_solver=ode_solver,
        use_sx=use_sx,
        n_threads=n_threads,
    )


def main():
    """
    If pendulum is run as a script, it will perform the optimization and animates it
    """

    # --- First pass --- #
    # --- Prepare the ocp --- #
    ocp_first = prepare_ocp_first_pass(
        biorbd_model_path="models/pendulum_maze.bioMod", final_time=5, n_shooting=500, n_threads=3
    )
    # ocp_first.print(to_console=True)

    solver_first = Solver.IPOPT(show_online_optim=True, show_options=dict(show_bounds=True))
    # change maximum iterations to affect the initial solution
    # it doesn't mather if it exits before the optimal solution, only that there is an initial guess
    solver_first.set_maximum_iterations(500)

    # Custom plots
    # ocp_first.add_plot_penalty(CostType.OBJECTIVES)

    # --- Solve the ocp --- #
    sol_first = ocp_first.solve(solver_first)
    # sol.graphs()

    # # --- Second pass ---#
    # # --- Prepare the ocp --- #
    solver_second = Solver.IPOPT(show_online_optim=True, show_options=dict(show_bounds=True))
    solver_second.set_maximum_iterations(1000)

    ocp_second = prepare_ocp_second_pass(
        biorbd_model_path="models/pendulum_maze.bioMod", solution=sol_first, final_time=5, n_threads=3
    )

    # Custom plots
    # ocp_second.add_plot_penalty(CostType.CONSTRAINTS)

    # --- Solve the ocp --- #
    sol_second = ocp_second.solve(solver_second)
    # sol.graphs()

    # --- Show the results in a bioviz animation --- #
    sol_first.detailed_cost_values()
    sol_first.print_cost()
    sol_first.animate(n_frames=100)

    sol_second.detailed_cost_values()
    sol_second.print_cost()
    sol_second.animate(n_frames=100)


if __name__ == "__main__":
    main()
