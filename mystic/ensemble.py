#!/usr/bin/env python
#
# Author: Mike McKerns (mmckerns @caltech and @uqfoundation)
# Copyright (c) 1997-2014 California Institute of Technology.
# License: 3-clause BSD.  The full license text is available at:
#  - http://trac.mystic.cacr.caltech.edu/project/mystic/browser/mystic/LICENSE
"""
Solvers
=======

This module contains a collection of optimization routines that use "map"
to distribute several optimizer instances over parameter space. Each
solver accepts a imported solver object as the "nested" solver, which
becomes the target of the map function.

The set of solvers built on mystic's AbstractEnsembleSolver are::
   LatticeSolver -- start from center of N grid points
   BuckshotSolver -- start from N random points in parameter space


Usage
=====

See `mystic.examples.buckshot_example06` for an example of using
BuckshotSolver. See `mystic.examples.lattice_example06`
or an example of using LatticeSolver.

All solvers included in this module provide the standard signal handling.
For more information, see `mystic.mystic.abstract_solver`.
"""
__all__ = ['LatticeSolver','BuckshotSolver']

from mystic.tools import wrap_function

from mystic.abstract_ensemble_solver import AbstractEnsembleSolver


class LatticeSolver(AbstractEnsembleSolver):
    """
parallel mapped optimization starting from the center of N grid points
    """
    def __init__(self, dim, nbins):
        """
Takes two initial inputs: 
    dim   -- dimensionality of the problem
    nbins -- tuple of number of bins in each dimension

All important class members are inherited from AbstractEnsembleSolver.
        """
        super(LatticeSolver, self).__init__(dim, nbins=nbins)
        from mystic.termination import NormalizedChangeOverGeneration
        convergence_tol = 1e-4
        self._termination = NormalizedChangeOverGeneration(convergence_tol)

#   def SetGridBins(self, nbins):
#       return

    #FIXME: should take cost=None, ExtraArgs=None... and utilize Step
    def Solve(self, cost, termination=None, sigint_callback=None,
                                            ExtraArgs=(), **kwds):
        """Minimize a function using batch grid optimization.

Description:

    Uses parallel mapping of solvers on a regular grid to find the
    minimum of a function of one or more variables.

Inputs:

    cost -- the Python function or method to be minimized.

Additional Inputs:

    termination -- callable object providing termination conditions.
    sigint_callback -- callback function for signal handler.
    ExtraArgs -- extra arguments for cost.

Further Inputs:

    callback -- an optional user-supplied function to call after each
        iteration.  It is called as callback(xk), where xk is the
        current parameter vector.                           [default = None]
    disp -- non-zero to print convergence messages.         [default = 0]
        """
        # process and activate input settings
        settings = self._process_inputs(kwds)
        disp=0
#       for key in settings:
#           exec "%s = settings['%s']" % (key,key)
        if disp in ['verbose', 'all']: verbose = True
        else: verbose = False
        #-------------------------------------------------------------

        import signal
       #self._EARLYEXIT = False

       #FIXME: EvaluationMonitor fails for MPI, throws error for 'pp'
        from python_map import python_map
        if self._map != python_map:
            self._fcalls = [0] #FIXME: temporary patch for removing the following line
        else:
            self._fcalls, cost = wrap_function(cost, ExtraArgs, self._evalmon)

        #generate signal_handler
        self._generateHandler(sigint_callback) 
        if self._handle_sigint: signal.signal(signal.SIGINT,self.signal_handler)

        # register termination function
        if termination is not None:
            self.SetTermination(termination)

        # get the nested solver instance
        solver = self._AbstractEnsembleSolver__get_solver_instance()
        #-------------------------------------------------------------

        nbins = self._nbins
        if len(self._strictMax): upper = list(self._strictMax)
        else:
            upper = list(self._defaultMax)
        if len(self._strictMin): lower = list(self._strictMin)
        else:
            lower = list(self._defaultMin)

        # generate arrays of points defining a grid in parameter space
        grid_dimensions = self.nDim
        bins = []
        for i in range(grid_dimensions):
            step = abs(upper[i] - lower[i])/nbins[i]
            bins.append( [lower[i] + (j+0.5)*step for j in range(nbins[i])] )

        # build a grid of starting points
        from mystic.math import gridpts
        initial_values = gridpts(bins)

        # run optimizer for each grid point
        from copy import deepcopy as copy
        op = [copy(solver) for i in range(len(initial_values))]
       #cf = [cost for i in range(len(initial_values))]
       #vb = [verbose for i in range(len(initial_values))]
        id = range(len(initial_values))

        # generate the local_optimize function
        def local_optimize(solver, x0, rank=None, disp=verbose):
            solver.id = rank
            solver.SetInitialPoints(x0)
            if solver._useStrictRange: #XXX: always, settable, or sync'd ?
                solver.SetStrictRanges(min=solver._strictMin, \
                                       max=solver._strictMax) # or lower,upper ?
            solver.Solve(cost, disp=disp)
            return solver

        # map:: solver = local_optimize(solver, x0, id, verbose)
        results = self._map(local_optimize, op, initial_values, id, \
                                                **self._mapconfig)

        # save initial state
        self._AbstractSolver__save_state()
        # get the results with the lowest energy
        self._bestSolver = results[0]
        bestpath = self._bestSolver._stepmon
        besteval = self._bestSolver._evalmon
        self._total_evals = self._bestSolver.evaluations
        for solver in results[1:]:
            self._total_evals += solver.evaluations # add func evals
            if solver.bestEnergy < self._bestSolver.bestEnergy:
                self._bestSolver = solver
                bestpath = solver._stepmon
                besteval = solver._evalmon

        # return results to internals
        self.population = self._bestSolver.population #XXX: pointer? copy?
        self.popEnergy = self._bestSolver.popEnergy #XXX: pointer? copy?
        self.bestSolution = self._bestSolver.bestSolution #XXX: pointer? copy?
        self.bestEnergy = self._bestSolver.bestEnergy
        self.trialSolution = self._bestSolver.trialSolution #XXX: pointer? copy?
        self._fcalls = self._bestSolver._fcalls #XXX: pointer? copy?
        self._maxiter = self._bestSolver._maxiter
        self._maxfun = self._bestSolver._maxfun

        # write 'bests' to monitors  #XXX: non-best monitors may be useful too
        self._stepmon = bestpath #XXX: pointer? copy?
        self._evalmon = besteval #XXX: pointer? copy?
       #from mystic.tools import isNull
       #if isNull(bestpath):
       #    self._stepmon = bestpath
       #else:
       #    for i in range(len(bestpath.y)):
       #        self._stepmon(bestpath.x[i], bestpath.y[i], self.id)
       #        #XXX: could apply callback here, or in exec'd code
       #if isNull(besteval):
       #    self._evalmon = besteval
       #else:
       #    for i in range(len(besteval.y)):
       #        self._evalmon(besteval.x[i], besteval.y[i])
        #-------------------------------------------------------------

        signal.signal(signal.SIGINT,signal.default_int_handler)

        # log any termination messages
        msg = self.CheckTermination(disp=disp, info=True)
        if msg: self._stepmon.info('STOP("%s")' % msg)
        # save final state
        self._AbstractSolver__save_state(force=True)
        return 

class BuckshotSolver(AbstractEnsembleSolver):
    """
parallel mapped optimization starting from the N random points
    """
    def __init__(self, dim, npts):
        """
Takes two initial inputs: 
    dim   -- dimensionality of the problem
    npts  -- number of parallel solver instances

All important class members are inherited from AbstractEnsembleSolver.
        """
        super(BuckshotSolver, self).__init__(dim, npts=npts)
        from mystic.termination import NormalizedChangeOverGeneration
        convergence_tol = 1e-4
        self._termination = NormalizedChangeOverGeneration(convergence_tol)

    def Solve(self, cost, termination=None, sigint_callback=None,
                                            ExtraArgs=(), **kwds):
        """Minimize a function using buckshot optimization.

Description:

    Uses parallel mapping of solvers on randomly selected points
    to find the minimum of a function of one or more variables.

Inputs:

    cost -- the Python function or method to be minimized.

Additional Inputs:

    termination -- callable object providing termination conditions.
    sigint_callback -- callback function for signal handler.
    ExtraArgs -- extra arguments for cost.

Further Inputs:

    callback -- an optional user-supplied function to call after each
        iteration.  It is called as callback(xk), where xk is the
        current parameter vector.                           [default = None]
    disp -- non-zero to print convergence messages.         [default = 0]
        """
        # process and activate input settings
        settings = self._process_inputs(kwds)
        disp=0
#       for key in settings:
#           exec "%s = settings['%s']" % (key,key)
        if disp in ['verbose', 'all']: verbose = True
        else: verbose = False
        #-------------------------------------------------------------

        import signal
       #self._EARLYEXIT = False

       #FIXME: EvaluationMonitor fails for MPI, throws error for 'pp'
        from python_map import python_map
        if self._map != python_map:
            self._fcalls = [0] #FIXME: temporary patch for removing the following line
        else:
            self._fcalls, cost = wrap_function(cost, ExtraArgs, self._evalmon)

        #generate signal_handler
        self._generateHandler(sigint_callback) 
        if self._handle_sigint: signal.signal(signal.SIGINT,self.signal_handler)

        # register termination function
        if termination is not None:
            self.SetTermination(termination)

        # get the nested solver instance
        solver = self._AbstractEnsembleSolver__get_solver_instance()
        #-------------------------------------------------------------

        npts = self._npts
        if len(self._strictMax): upper = list(self._strictMax)
        else:
            upper = list(self._defaultMax)
        if len(self._strictMin): lower = list(self._strictMin)
        else:
            lower = list(self._defaultMin)

        # generate a set of starting points
        from mystic.math import samplepts
        initial_values = samplepts(lower,upper,npts)

        # run optimizer for each grid point
        from copy import deepcopy as copy
        op = [copy(solver) for i in range(len(initial_values))]
       #cf = [cost for i in range(len(initial_values))]
       #vb = [verbose for i in range(len(initial_values))]
        id = range(len(initial_values))

        # generate the local_optimize function
        def local_optimize(solver, x0, rank=None, disp=verbose):
            solver.id = rank
            solver.SetInitialPoints(x0)
            if solver._useStrictRange: #XXX: always, settable, or sync'd ?
                solver.SetStrictRanges(min=solver._strictMin, \
                                       max=solver._strictMax) # or lower,upper ?
            solver.Solve(cost, disp=disp)
            return solver

        # map:: solver = local_optimize(solver, x0, id, verbose)
        results = self._map(local_optimize, op, initial_values, id, \
                                                **self._mapconfig)

        # save initial state
        self._AbstractSolver__save_state()
        # get the results with the lowest energy
        self._bestSolver = results[0]
        bestpath = self._bestSolver._stepmon
        besteval = self._bestSolver._evalmon
        self._total_evals = self._bestSolver.evaluations
        for solver in results[1:]:
            self._total_evals += solver.evaluations # add func evals
            if solver.bestEnergy < self._bestSolver.bestEnergy:
                self._bestSolver = solver
                bestpath = solver._stepmon
                besteval = solver._evalmon

        # return results to internals
        self.population = self._bestSolver.population #XXX: pointer? copy?
        self.popEnergy = self._bestSolver.popEnergy #XXX: pointer? copy?
        self.bestSolution = self._bestSolver.bestSolution #XXX: pointer? copy?
        self.bestEnergy = self._bestSolver.bestEnergy
        self.trialSolution = self._bestSolver.trialSolution #XXX: pointer? copy?
        self._fcalls = self._bestSolver._fcalls #XXX: pointer? copy?
        self._maxiter = self._bestSolver._maxiter
        self._maxfun = self._bestSolver._maxfun

        # write 'bests' to monitors  #XXX: non-best monitors may be useful too
        self._stepmon = bestpath #XXX: pointer? copy?
        self._evalmon = besteval #XXX: pointer? copy?
       #from mystic.tools import isNull
       #if isNull(bestpath):
       #    self._stepmon = bestpath
       #else:
       #    for i in range(len(bestpath.y)):
       #        self._stepmon(bestpath.x[i], bestpath.y[i], self.id)
       #        #XXX: could apply callback here, or in exec'd code
       #if isNull(besteval):
       #    self._evalmon = besteval
       #else:
       #    for i in range(len(besteval.y)):
       #        self._evalmon(besteval.x[i], besteval.y[i])
        #-------------------------------------------------------------

        signal.signal(signal.SIGINT,signal.default_int_handler)

        # log any termination messages
        msg = self.CheckTermination(disp=disp, info=True)
        if msg: self._stepmon.info('STOP("%s")' % msg)
        # save final state
        self._AbstractSolver__save_state(force=True)
        return 


def lattice(cost,ndim,nbins=2,args=(),bounds=None,ftol=1e-4,maxiter=None, \
            maxfun=None,full_output=0,disp=1,retall=0,callback=None,**kwds):
    """Minimize a function using the lattice ensemble solver.
    
Description:

    Uses a lattice ensemble algorithm to find the minimum of
    a function of one or more variables. Mimics the scipy.optimize.fmin
    interface. Starts N solver instances at regular intervals in parameter
    space, determined by 'nbins' (N = numpy.prod(nbins); len(nbins) == ndim). 

Inputs:

    cost -- the Python function or method to be minimized.
    ndim -- dimensionality of the problem.
    nbins -- tuple of number of bins in each dimension.

Additional Inputs:

    args -- extra arguments for cost.
    bounds -- list - n pairs of bounds (min,max), one pair for each parameter.
    ftol -- number - acceptable relative error in cost(xopt) for convergence.
    gtol -- number - maximum number of iterations to run without improvement.
    maxiter -- number - the maximum number of iterations to perform.
    maxfun -- number - the maximum number of function evaluations.
    full_output -- number - non-zero if fval and warnflag outputs are desired.
    disp -- number - non-zero to print convergence messages.
    retall -- number - non-zero to return list of solutions at each iteration.
    callback -- an optional user-supplied function to call after each
        iteration.  It is called as callback(xk), where xk is the
        current parameter vector.
    solver -- solver - override the default nested Solver instance.
    handler -- boolean - enable/disable handling of interrupt signal.
    itermon -- monitor - override the default GenerationMonitor.
    evalmon -- monitor - override the default EvaluationMonitor.
    constraints -- an optional user-supplied function.  It is called as
        constraints(xk), where xk is the current parameter vector.
        This function must return xk', a parameter vector that satisfies
        the encoded constraints.
    penalty -- an optional user-supplied function.  It is called as
        penalty(xk), where xk is the current parameter vector.
        This function should return y', with y' == 0 when the encoded
        constraints are satisfied, and y' > 0 otherwise.

Returns: (xopt, {fopt, iter, funcalls, warnflag, allfuncalls}, {allvecs})

    xopt -- ndarray - minimizer of function
    fopt -- number - value of function at minimum: fopt = cost(xopt)
    iter -- number - number of iterations
    funcalls -- number - number of function calls
    warnflag -- number - Integer warning flag:
        1 : 'Maximum number of function evaluations.'
        2 : 'Maximum number of iterations.'
    allfuncalls -- number - total function calls (for all solver instances)
    allvecs -- list - a list of solutions at each iteration

    """
    handler = False
    if kwds.has_key('handler'):
        handler = kwds['handler']
    from mystic.solvers import NelderMeadSimplexSolver as _solver
    if kwds.has_key('solver'):
        _solver = kwds['solver']

    from mystic.monitors import Monitor
    stepmon = Monitor()
    evalmon = Monitor()
    if kwds.has_key('itermon'):
        stepmon = kwds['itermon']
    if kwds.has_key('evalmon'):
        evalmon = kwds['evalmon']

    gtol = 10 # termination generations (scipy: 2, default: 10)
    if kwds.has_key('gtol'):
        gtol = kwds['gtol']
    if gtol: #if number of generations is provided, use NCOG
        from mystic.termination import NormalizedChangeOverGeneration
        termination = NormalizedChangeOverGeneration(ftol,gtol)
    else:
        from mystic.termination import VTRChangeOverGeneration
        termination = VTRChangeOverGeneration(ftol)

    if isinstance(nbins, int): nbins = [nbins]*ndim

    solver = LatticeSolver(ndim,nbins)
    solver.SetNestedSolver(_solver) #XXX: skip settings for configured solver?
    solver.SetEvaluationLimits(maxiter,maxfun)
    solver.SetEvaluationMonitor(evalmon)
    solver.SetGenerationMonitor(stepmon)
    if kwds.has_key('penalty'):
        penalty = kwds['penalty']
        solver.SetPenalty(penalty)
    if kwds.has_key('constraints'):
        constraints = kwds['constraints']
        solver.SetConstraints(constraints)
    if bounds is not None:
        minb,maxb = unpair(bounds)
        solver.SetStrictRanges(minb,maxb)

    if handler: solver.enable_signal_handler()
    solver.Solve(cost,termination=termination,disp=disp, \
                 ExtraArgs=args,callback=callback)
    solution = solver.Solution()

    # code below here pushes output to scipy.optimize.fmin interface
    msg = solver.CheckTermination(disp=disp, info=True)

    x = solver.bestSolution
    fval = solver.bestEnergy
    warnflag = 0
    fcalls = solver.evaluations
    all_fcalls = solver._total_evals
    iterations = max(0,len(solver._stepmon.y)-1) #FIXME: solver.generations
    allvecs = solver._stepmon.x

    if fcalls >= solver._maxfun: #XXX: check against total or individual?
        warnflag = 1
    elif iterations >= solver._maxiter: #XXX: check against total or individual?
        warnflag = 2
    else: pass

    if full_output:
        retlist = x, fval, iterations, fcalls, warnflag, all_fcalls
        if retall:
            retlist += (allvecs,)
    else:
        retlist = x
        if retall:
            retlist = (x, allvecs)

    return retlist


def buckshot(cost,ndim,npts=8,args=(),bounds=None,ftol=1e-4,maxiter=None, \
             maxfun=None,full_output=0,disp=1,retall=0,callback=None,**kwds):
    """Minimize a function using the buckshot ensemble solver.
    
Description:

    Uses a buckshot ensemble algorithm to find the minimum of
    a function of one or more variables. Mimics the scipy.optimize.fmin
    interface. Starts 'npts' solver instances at random points in parameter
    space. 

Inputs:

    cost -- the Python function or method to be minimized.
    ndim -- dimensionality of the problem.
    npts -- number of solver instances.

Additional Inputs:

    args -- extra arguments for cost.
    bounds -- list - n pairs of bounds (min,max), one pair for each parameter.
    ftol -- number - acceptable relative error in cost(xopt) for convergence.
    gtol -- number - maximum number of iterations to run without improvement.
    maxiter -- number - the maximum number of iterations to perform.
    maxfun -- number - the maximum number of function evaluations.
    full_output -- number - non-zero if fval and warnflag outputs are desired.
    disp -- number - non-zero to print convergence messages.
    retall -- number - non-zero to return list of solutions at each iteration.
    callback -- an optional user-supplied function to call after each
        iteration.  It is called as callback(xk), where xk is the
        current parameter vector.
    solver -- solver - override the default nested Solver instance.
    handler -- boolean - enable/disable handling of interrupt signal.
    itermon -- monitor - override the default GenerationMonitor.
    evalmon -- monitor - override the default EvaluationMonitor.
    constraints -- an optional user-supplied function.  It is called as
        constraints(xk), where xk is the current parameter vector.
        This function must return xk', a parameter vector that satisfies
        the encoded constraints.
    penalty -- an optional user-supplied function.  It is called as
        penalty(xk), where xk is the current parameter vector.
        This function should return y', with y' == 0 when the encoded
        constraints are satisfied, and y' > 0 otherwise.

Returns: (xopt, {fopt, iter, funcalls, warnflag, allfuncalls}, {allvecs})

    xopt -- ndarray - minimizer of function
    fopt -- number - value of function at minimum: fopt = cost(xopt)
    iter -- number - number of iterations
    funcalls -- number - number of function calls
    warnflag -- number - Integer warning flag:
        1 : 'Maximum number of function evaluations.'
        2 : 'Maximum number of iterations.'
    allfuncalls -- number - total function calls (for all solver instances)
    allvecs -- list - a list of solutions at each iteration

    """
    handler = False
    if kwds.has_key('handler'):
        handler = kwds['handler']
    from mystic.solvers import NelderMeadSimplexSolver as _solver
    if kwds.has_key('solver'):
        _solver = kwds['solver']

    from mystic.monitors import Monitor
    stepmon = Monitor()
    evalmon = Monitor()
    if kwds.has_key('itermon'):
        stepmon = kwds['itermon']
    if kwds.has_key('evalmon'):
        evalmon = kwds['evalmon']

    gtol = 10 # termination generations (scipy: 2, default: 10)
    if kwds.has_key('gtol'):
        gtol = kwds['gtol']
    if gtol: #if number of generations is provided, use NCOG
        from mystic.termination import NormalizedChangeOverGeneration
        termination = NormalizedChangeOverGeneration(ftol,gtol)
    else:
        from mystic.termination import VTRChangeOverGeneration
        termination = VTRChangeOverGeneration(ftol)

    solver = BuckshotSolver(ndim,npts)
    solver.SetNestedSolver(_solver) #XXX: skip settings for configured solver?
    solver.SetEvaluationLimits(maxiter,maxfun)
    solver.SetEvaluationMonitor(evalmon)
    solver.SetGenerationMonitor(stepmon)
    if kwds.has_key('penalty'):
        penalty = kwds['penalty']
        solver.SetPenalty(penalty)
    if kwds.has_key('constraints'):
        constraints = kwds['constraints']
        solver.SetConstraints(constraints)
    if bounds is not None:
        minb,maxb = unpair(bounds)
        solver.SetStrictRanges(minb,maxb)

    if handler: solver.enable_signal_handler()
    solver.Solve(cost,termination=termination,disp=disp, \
                 ExtraArgs=args,callback=callback)
    solution = solver.Solution()

    # code below here pushes output to scipy.optimize.fmin interface
    msg = solver.CheckTermination(disp=disp, info=True)

    x = solver.bestSolution
    fval = solver.bestEnergy
    warnflag = 0
    fcalls = solver.evaluations
    all_fcalls = solver._total_evals
    iterations = max(0,len(solver._stepmon.y)-1) #FIXME: solver.generations
    allvecs = solver._stepmon.x

    if fcalls >= solver._maxfun: #XXX: check against total or individual?
        warnflag = 1
    elif iterations >= solver._maxiter: #XXX: check against total or individual?
        warnflag = 2
    else: pass

    if full_output:
        retlist = x, fval, iterations, fcalls, warnflag, all_fcalls
        if retall:
            retlist += (allvecs,)
    else:
        retlist = x
        if retall:
            retlist = (x, allvecs)

    return retlist



# backward compatibility
ScattershotSolver = BuckshotSolver
BatchGridSolver = LatticeSolver


if __name__=='__main__':
    help(__name__)

# end of file
