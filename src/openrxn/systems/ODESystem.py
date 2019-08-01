"""ODE systems have continuous values for species quantities
and are propagated forward in time using ODE solvers like
scipy's solve_idp function."""

from openrxn import unit
from openrxn.systems.state import State
from openrxn.systems.deriv import DerivFuncBuilder
from openrxn.systems.system import System

from scipy.integrate import solve_ivp
import numpy as np
import logging

EPSILON = 1e-8

class ODESystem(System):

    def __init__(self, *args, **kwargs):

        super().__init__(*args,**kwargs)
        self.NA = 6.022e23
        
        self.dqdt = self._build_dqdt()

    def set_q(self,idxs,Q):
        """Set the state.q_val array at the specified indexes
        to the value Q.

        idxs : list, int
        List of indexes to set.

        Q  : Quantity 
        If unitless, assumed to be number counts of species
        If mol/L is passed, it uses compartment values to
        convert to mol.
        """

        mult_volume = False
        mult_na = False
        if hasattr(Q,'units'):
            if Q.units == unit.mol/unit.L:
                mult_volume = True
                mult_na = True
            elif Q.units == unit.mol:
                mult_na = True
            elif Q.units != unit.dimensionless:
                raise ValueError("Quantity values should be either mol, mol/L or dimensionless")
        else:
            Q *= unit.dimensionless
 
        for i in idxs:
            if mult_volume:
                tmp = self.model.compartments[self.state.compartment[i]].volume * Q
            else:
                tmp = Q
            if mult_na:
                tmp *= self.NA

            # removing units for q_val array (cast in units of numbers of molecules)
            self.state.q_val[i] = tmp.magnitude
        
    def _build_dqdt(self):
        """Uses a model to build a list of derivative functions, with 
        indices that are consistent with the state vector.  self.dqdt[i], 
        calculates the rate of change of self.q_val[i] .

        Formulates each derivative equation as:
        
        dq[i]/dt =  sum_{j in sources}  k_j * prod_{k} q_k
                  - sum_{j in sinks}    k_j * prod_{k} q_k

        To construct the derivative function, it passes a list of 
        sources, where the elements of the list are:

        (k_j, [q_k0, q_k1...])

        and a similar list of sinks.  The rates passed are in units of s^-1.

        Inputs:
        
        state : openrxn.systems.state.State object
        model : openrxn.model.FlatModel object
        """
        dqdt = []
        for i in range(self.state.size):
            # collect source and sink terms for this species in this compartment

            c = self.model.compartments[self.state.compartment[i]]
            s = self.state.species[i]

            sources = []
            sinks = []
            
            # look through the reactions in this compartment for ones that
            # involve this species
            for r in c.reactions:
                if s in r.reactant_IDs:
                    if r.kf > 0:
                        # append forward reaction to sinks
                        q_list = []
                        n_r = 0
                        for j,x in enumerate(r.reactants):
                            q_list += [self.state.index[c.ID][x.ID]]*r.stoich_r[j]
                            n_r += r.stoich_r[j]
                        if n_r - 1 > 0:
                            vol_fac = c.volume**(n_r-1)
                            sinks.append((r.kf/vol_fac,q_list))
                        else:
                            sinks.append((r.kf,q_list))

                    if r.kr > 0:
                        # append reverse reaction to sources
                        q_list = []
                        n_p = 0
                        for j,x in enumerate(r.products):
                            q_list += [self.state.index[c.ID][x.ID]]*r.stoich_p[j]
                            n_p += r.stoich_p[j]
                        if n_p - 1 > 0:
                            vol_fac = c.volume**(n_p-1)
                            sources.append((r.kr/vol_fac,q_list))
                        else:
                            sources.append((r.kr,q_list))
                    
                elif s in r.product_IDs:
                    if r.kf > 0:
                        # append forward reaction to sources
                        q_list = []
                        n_r = 0
                        for j,x in enumerate(r.reactants):
                            q_list += [self.state.index[c.ID][x.ID]]*r.stoich_r[j]
                            n_r += r.stoich_r[j]
                        if n_r - 1 > 0:
                            vol_fac = c.volume**(n_r-1)
                            sources.append((r.kf/vol_fac,q_list))
                        else:
                            sources.append((r.kf,q_list))

                    if r.kr > 0:
                        # append reverse reaction to sinks
                        q_list = []
                        n_p = 0
                        for j,x in enumerate(r.products):
                            q_list += [self.state.index[c.ID][x.ID]]*r.stoich_p[j]
                            n_p += r.stoich_p[j]
                        if n_p - 1 > 0:
                            vol_fac = c.volume**(n_p-1)
                            sinks.append((r.kr/vol_fac,q_list))
                        else:
                            sinks.append((r.kr,q_list))

            # look through connections for those that involve this species
            for other_lab, conn in c.connections.items():
                if s in conn[1].species_rates:
                    # add "out" diffusion process
                    sinks.append((conn[1].species_rates[s][0]/c.volume,[i]))

                    # add "in" diffusion process
                    sources.append((conn[1].species_rates[s][1]/conn[0].volume,[self.state.index[other_lab][s]]))
                    
            dqdt.append(DerivFuncBuilder(sources, sinks))

        return dqdt
                            
    def _dQ_dt(self,t,Q):
        return np.array([builder.deriv_func(Q,t) for builder in self.dqdt])
    
    def propagate(self,t_interval,**kwargs):
        """For ODE systems, propagate directly calls the scipy
        solve_ivp function.  state.q_val is also updated."""

        result = solve_ivp(self._dQ_dt,t_interval,self.state.q_val,**kwargs)
        self.state.q_val = result.y[:,-1]
        
        return result