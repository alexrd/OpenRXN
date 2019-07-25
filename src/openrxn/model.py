"""A model is a given set of compartments and reactions.
New models can either be build by adding compartments and
reactions one at a time, or a new model can be defined 
using a template, and then edited.
"""

from openrxn.compartments.compartment import Compartment
from openrxn.reactions import Reaction
from openrxn.compartments.ID import makeID
from openrxn.connections import FicksConnection
import numpy as np
from math import sqrt

class Model(object):
    """Models can hold both compartments and compartment 
    arrays. In order to be exported to a graph representation
    or to a System object they must be flattened into a 
    FlatModel, which has only compartments.

    Diffusion rates between compartments can be specified
    through FicksConnections, which are quantified upon 
    flattening.
    """

    def __init__(self, arrays=[], compartments=[]):
        self.compartments = {}
        self.arrays = {}

        self.periodic = None
        self.box_len = None
        
        for a in arrays:
            self.add_array(a)

        for c in compartments:
            self.add_compartment(c)


    def add_array(self,array):
        if self.periodic is None:
            self.periodic = array.periodic
        else:
            if self.periodic != array.periodic:
                raise ValueError("Error! Adding array with incompatible periodicity to model ({0}) ({1})".format(self.periodic,array.periodic))

        if self.box_len is None:
            self.box_len = array.box_len
        else:
            for i in range(len(array.box_len)):
                # loop over dimensions
                if self.box_len[i] != array.box_len[i]:
                    if self.periodic[i]:
                        raise ValueError("Error! Adding array with different size along a periodic dimension ({0}) ({1})".format(self.box_len[i],array.box_len[i]))
                    else:
                        # assume stacking behavior
                        self.box_len[i] += array.box_len[i]

        if array.array_ID in self.arrays.keys():
            raise ValueError("Error! Duplicate array ID in model ({0})".format(array.array_ID))
        self.arrays[array.array_ID] = array


    def add_compartment(self,compartment):
        if compartment.ID in self.compartments.keys():
            raise ValueError("Error! Duplicate compartment ID in model ({0})".format(compartment.ID))
        self.comparments[compartment.ID] = compartment

    def flatten(self):
        """Returns a FlatModel, where all compartment array
        information is lost, and all FicksConnections are 
        resolved."""

        # initialize model
        flatmodel = FlatModel()

        # add compartments
        flatmodel.add_compartments(self.compartments.values())

        for a in self.arrays.values():
            flatmodel.add_compartments(a.compartments.values())

        # check for missing compartments
        missing = flatmodel.find_missing_compartments()
        if len(missing) > 0:
            raise ValueError("Error! The following compartments are referred to in connections, but missing from the model: {0}".format(missing))

        # resolve FicksConnections
        for c in flatmodel.compartments.values():
            for label,conn in c.connections.items():
                # conn is a tuple (other_connection, connection)
                if isinstance(conn[1],FicksConnection):
                    self.resolve_ficks(c,conn[0],conn[1])

        return flatmodel

    def resolve_ficks(self,c1,c2,conn):
        """If surface area and inter-compartment distance are not attached
        to the FicksConnection, this function will attempt to compute them
        using the compartment positions and Array properties.

        Note that the surface area calculation only works for cubic compartments
        that are fully adjoining on one face.

        This function then calls the resolve method of the FicksConnection and
        returns the corresponding IsotropicConnection."""

        pos1 = c1.pos
        pos2 = c2.pos

        if conn.surface_area is None:
            # compute surface area
            if pos1[0][1] == pos2[0][0] or pos1[0][0] == pos2[0][1]:
                # adjoining x; use y,z face area
                conn.surface_area = min(c1.surface_area['yz'],
                                        c2.surface_area['yz'])
            elif pos1[1][1] == pos2[1][0] or pos1[1][0] == pos2[1][1]:
                # adjoining y; use x,z face area
                conn.surface_area = min(c1.surface_area['xz'],
                                        c2.surface_area['xz'])
            elif pos1[2][1] == pos2[2][0] or pos1[2][0] == pos2[2][1]:
                # adjoining z; use x,y face area
                conn.surface_area = min(c1.surface_area['xy'],
                                        c2.surface_area['xy'])
            else:
                raise ValueError("Error! Unable to determine adjoining face for regions: ({0}) and ({1})".format(pos1,pos2))
        if conn.ic_distance is None:
            # compute inter-compartment distance
            d = [0,0,0]
            for i in range(len(d)):
                d[i] = (0.5*(pos1[i][0]+pos1[i][1])-
                        0.5*(pos2[i][0]+pos2[i][1]))
                  
            # get inter-compartmental distance
            conn.ic_distance = 0
            for i,dc in enumerate(d):
                if self.periodic[i]:
                    if dc*2 < -self.box_len[i]:
                        dc += self.box_len[i]
                    elif dc*2 > self.box_len[i]:
                        dc -= self.box_len[i]
                conn.ic_distance += dc**2
            conn.ic_distance = np.sqrt(conn.ic_distance)

        new_conn = conn.resolve()
        c1.connect(c2,new_conn,warn_overwrite=False)
        c2.connect(c1,new_conn,warn_overwrite=False)

class FlatModel(object):
    """FlatModel objects have a flat set of compartments with
    quantified diffusion rate constants.  Each compartment is given
    a unique identifier.  If arrays were present, this identifier is:

    {array_ID}-{compartment_ID_string}

    where compartment_ID_string is the elements of the compartment ID tuple
    joined together with underscores.  (e.g. bulk-0_0_1)

    If arrays are not present then the identifiers are simply the 
    compartment IDs."""

    def __init__(self):
        self.compartments = {}

    def add_compartment(self,compartment):
        newID = makeID(compartment.array_ID,compartment.ID)
        if newID in self.compartments.keys():
            raise ValueError("Error! Duplicate compartment ID in model ({0})".format(newID))
        self.compartments[newID] = compartment.copy(ID=newID,delete_array_ID=True)

    def add_compartments(self,compartments):
        for c in compartments:
            self.add_compartment(c)

    def find_missing_compartments(self):
        """Returns a list of missing compartment IDs."""
        
        missing = []
        for c in self.compartments.values():
            for nbor in c.connections.keys():
                if nbor not in self.compartments:
                    missing.append(nbor)

        return missing

    def add_rxn(self,rxn,compartments='all'):
        """Adds a reaction to a set of compartments.
        
        rxn - Reaction to add.  Must be a Reaction object.
        
        compartments - Either the string 'all' or a list of compartment
                       IDs."""

        if compartments == 'all':
            comp_list = self.compartments.keys()
        else:
            comp_list = compartments

        for c in comp_list:
            assert c in self.compartments, "Error! compartment {0} is not in Model".format(c)
            self.compartments[c].add_rxn_to_compartment(rxn)
    
