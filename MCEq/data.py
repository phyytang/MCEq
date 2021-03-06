# -*- coding: utf-8 -*-
"""
:mod:`MCEq.data` --- data management
====================================

This module includes code for bookkeeping, interfacing and 
validating data structures:

- :class:`InteractionYields` manages particle interactions, obtained
  from sampling of various interaction models
- :class:`DecayYields` manages particle decays, obtained from 
  sampling PYTHIA8 Monte Carlo
- :class:`HadAirCrossSections` keeps information about the inelastic, 
  cross-section of hadrons with air. Typically obtained from Monte Carlo.
- :class:`NCEParticle` bundles different particle properties for simpler 
  usage in :class:`MCEqRun`
- :class:`EdepZFactos` calculates energy-dependent spectrum weighted
  moments (Z-Factors)
  
"""

import numpy as np
from mceq_config import config, dbg


class NCEParticle():

    """Bundles different particle properties for simplified 
    availability of particle properties in :class:`MCEq.core.MCEqRun`.

    Args:
      pdgid (int): PDG ID of the particle
      particle_db (object): handle to an instance of :class:`ParticleDataTool.SibyllParticleTable`
      pythia_db (object): handle to an instance of :class:`ParticleDataTool.PYTHIAParticleData`
      cs_db (object): handle to an instance of :class:`InteractionYields`
      d (int): dimension of the energy grid 
    """

    def __init__(self, pdgid, particle_db,
                 pythia_db, cs_db, d):

        #: (float) mixing energy, transition between hadron and resonance behavior
        self.E_mix = 0
        #: (int) energy grid index, where transition between hadron and resonance occurs
        self.mix_idx = 0
        #: (float) critical energy in air at the surface
        self.E_crit = 0

        #: (bool) particle is a hadron (meson or baryon)
        self.is_hadron = False
        #: (bool) particle is a meson
        self.is_meson = False
        #: (bool) particle is a baryon
        self.is_baryon = False
        #: (bool) particle is a lepton
        self.is_lepton = False
        #: (bool) particle is an alias (PDG ID encodes special scoring behavior)
        self.is_alias = False
        #: (bool) particle has both, hadron and resonance properties
        self.is_mixed = False
        #: (bool) if particle has just resonance behavior
        self.is_resonance = False
        #: (bool) particle is interacting projectile
        self.is_projectile = False

        self.pdgid = pdgid
        self.particle_db = particle_db
        self.pythia_db = pythia_db
        self.cs = cs_db
        self.d = d

        self.E_crit = self.critical_energy()
        self.name = particle_db.pdg2modname[pdgid]

        if pdgid in particle_db.mesons:
            self.is_hadron = True
            self.is_meson = True
        elif pdgid in particle_db.baryons:
            self.is_hadron = True
            self.is_baryon = True
        else:
            self.is_lepton = True
            if abs(pdgid) > 20:
                self.is_alias = True

    def hadridx(self):
        """Returns index range where particle behaves as hadron.

        Returns:
          :func:`tuple` (int,int): range on energy grid
        """
        return (self.mix_idx, self.d)

    def residx(self):
        """Returns index range where particle behaves as resonance.

        Returns:
          :func:`tuple` (int,int): range on energy grid
        """
        return (0, self.mix_idx)

    def lidx(self):
        """Returns lower index of particle range in state vector.

        Returns:
          (int): lower index in state vector :attr:`MCEqRun.phi`
        """
        return self.nceidx * self.d

    def uidx(self):
        """Returns upper index of particle range in state vector.

        Returns:
          (int): upper index in state vector :attr:`MCEqRun.phi`
        """
        return (self.nceidx + 1) * self.d

    def inverse_decay_length(self, E):
        """Returns inverse decay length (or infinity (np.inf), if 
        particle is stable), where the air density :math:`\\rho` is 
        factorized out.

        Args:
          E (float): energy in laboratory system in GeV 
        Returns:
          (float): :math:`\\frac{\\rho}{\\lambda_{dec}}` in 1/cm
        """
        try:
            dlen = self.pythia_db.mass(self.pdgid) / \
                self.pythia_db.ctau(self.pdgid) / E
            dlen[0:self.mix_idx] = 0.
            return dlen
        except:
            return np.ones(self.d) * np.inf

    def inverse_interaction_length(self, cs=None):
        """Returns inverse interaction length in Air.

        Returns:
          (float): :math:`\\frac{1}{\\lambda_{int}}` in cm**2/g
        """

        m_air = 14.5 * 1.672621 * 1e-24  # <A> * m_proton [g]
        return np.ones(self.d) * self.cs.get_cs(self.pdgid) / m_air

    def critical_energy(self):
        """Returns critical energy where decay and interaction
        are balanced.

        Approximate value in Air.

        Returns:
          (float): :math:`\\frac{m\\ 6.4 \\text{km}}{c\\tau}` in GeV
        """
        try:
            return self.pythia_db.mass(self.pdgid) * 6.4e5 / \
                self.pythia_db.ctau(self.pdgid)
        except ZeroDivisionError:
            return np.inf

    def calculate_mixing_energy(self, e_grid, no_mix=False):
        """Calculates interaction/decay length in Air and decides if 
        the particle has resonance and/or hadron behavior.

        Class attributes :attr:`is_mixed`, :attr:`E_mix`, :attr:`mix_idx`, 
        :attr:`is_resonance` are calculated here.

        Args:
          e_grid (np.array): energy grid of size :attr:`d`
          no_mix (bool): if True, mixing is disabled and all particles 
                         have either hadron or resonances behavior.
        """

        cross_over = config["hybrid_crossover"]

        if abs(self.pdgid) in [2212, 2112]:
            self.mix_idx = 0
            self.is_mixed = False
            return
        d = self.d

        inv_intlen = self.inverse_interaction_length()
        inv_declen = self.inverse_decay_length(e_grid)

        if not np.any(inv_declen > 0.) or not np.any(inv_intlen > 0.):
            self.mix_idx = 0
            self.is_mixed = False
            self.is_resonance = False
            return

        lint = np.ones(d) / inv_intlen
        d_tilde = 1 / self.inverse_decay_length(e_grid)

        # multiply with typical air density at the surface
        ldec = d_tilde * 1.240e-03

        criterium = ldec / lint

        if np.max(criterium) < cross_over:
            self.mix_idx = d - 1
            self.E_mix = e_grid[self.mix_idx]
            self.is_mixed = False
            self.is_resonance = True

        elif np.min(criterium) > cross_over or no_mix:
            self.mix_idx = 0
            self.is_mixed = False
            self.is_resonance = False
        else:
            self.mix_idx = np.where(ldec / lint > cross_over)[0][0]
            self.E_mix = e_grid[self.mix_idx]
            self.is_mixed = True
            self.is_resonance = False

    def __repr__(self):
        a_string = (
            """
        {0}: 
        is_hadron   : {1} 
        is_mixed    : {2}
        is_resonance: {3} 
        is_lepton   : {4}
        is_alias    : {5}
        E_mix       : {6:2.1e}\n""").format(
            self.name, self.is_hadron, self.is_mixed,
            self.is_resonance, self.is_lepton,
            self.is_alias, self.E_mix)
        return a_string

#         i(Ei0)->j(Ej0)    ...     i(EiN)->j(Ej0)
#         i(Ei0)->j(Ej1)    ...     i(EiN)->j(Ej1)
#             ...                        ...
#             ...                        ...
#             ...                        ...
#         i(Ei0)->j(EjN)   .....    i(EiN)->j(EjN)


def _decompress(fname):
    """Decompresses and unpickles dictionaries stored in bz2
    format.

    Args:
      fname (str): file name
    
    Returns:
      content of decompressed and unpickled file.

    Raises:
      IOError: if file not found

    """
    import os
    import bz2
    import cPickle as pickle
    fcompr = os.path.splitext(fname)[0] + '.bz2'

    if not os.path.isfile(fcompr):
        raise IOError('decompress():: File {0} not found.'.format(fcompr))
    
    if dbg > 1:
        print 'Decompressing', fcompr, '.'
    
    data = pickle.load(bz2.BZ2File(fcompr))
    pickle.dump(data, open(fname, 'w'), protocol=-1)

    return data

class InteractionYields():

    """Class for managing the dictionary of interaction yield matrices.

    The class unpickles a dictionary, which contains the energy grid 
    and :math:`x` spectra, sampled from hadronic interaction models.    



    A list of available interaction model keys can be printed by::

        $ print yield_obj

    Args:
      interaction_model (str): name of the interaction model
      charm_model (str, optional): name of the charm model

    """
    #: (str) InterAction Model name
    iam = None
    #: (str) charm model name
    charm_model = None
    #: (numpy.array) energy grid bin centers
    e_grid = None
    #: (numpy.array) energy grid bin endges
    e_bins = None
    #: (numpy.array) energy grid bin widths
    weights = None
    #: (int) dimension of grid
    dim = 0

    def __init__(self, interaction_model, charm_model=None):

        self._load()

        # If parameters are provided during object creation,
        # load the tables during object creation.
        if interaction_model != None:
            self.set_interaction_model(interaction_model)

        if charm_model and interaction_model:
            self.inject_custom_charm_model(charm_model)

    def _load(self):
        """Un-pickles the yields dictionary using the path specified as
        ``yield_fname`` in :mod:`mceq_config`.

        Class attributes :attr:`e_grid`, :attr:`e_bins`, :attr:`weights`, 
        :attr:`dim` are set here.

        Raises:
          IOError: if file not found
        """
        import cPickle as pickle
        from os.path import join
        try:
            with open(join(config['data_dir'],
                           config['yield_fname']), 'r') as f:
                self.yield_dict = pickle.load(f)
        except IOError:
            self.yield_dict = _decompress(join(config['data_dir'],
                                            config['yield_fname']))
            #raise IOError('InteractionYields::_load(): Yield file not found.')

        self.e_grid = self.yield_dict.pop('evec')
        self.e_bins = self.yield_dict.pop('ebins')
        self.weights = np.diag(self.e_bins[1:] - self.e_bins[:-1])
        self.dim = self.e_grid.size
        self.no_interaction = np.zeros(self.dim ** 2).reshape(
            self.dim, self.dim)

    def _gen_index(self, yield_dict):
        """Generates index of mother-daughter relationships.

        Currently this function is called each time an interaction model
        is set. In future versions this index will be part of the pickled
        dictionary.

        Args:
          yield_dict (dict): dictionary of yields for one interaction model
        """
        self.projectiles = np.unique(zip(*yield_dict.keys())[0])
        self.secondary_dict = {}
        for projectile in self.projectiles:
            self.secondary_dict[projectile] = []

        for key, mat in yield_dict.iteritems():
            proj, sec = key
            # exclude electrons and photons
            if np.sum(mat) > 0 and abs(sec) not in [11, 22]:
                assert(sec not in self.secondary_dict[proj]), \
                ("InteractionYields:_gen_index()::" +
                "Error in construction of index array: {0} -> {1}".format(proj, sec))
                self.secondary_dict[proj].append(sec)

    def set_interaction_model(self, interaction_model, force=False):
        """Selects an interaction model and prepares all internal variables. 

        Args:
          interaction_model (str): interaction model name
        Raises:
          Exception: if invalid name specified in argument ``interaction_model``
        """
        if not force and interaction_model == self.iam:
            if dbg > 0:
                print ("InteractionYields:set_interaction_model():: Model " +
                    self.iam + " already loaded.")
            return

        if interaction_model not in self.yield_dict.keys():
            raise Exception("InteractionYields(): No coupling matrices " +
                            "available for the selected interaction " +
                            "model: {0}.".format(interaction_model))

        self._gen_index(self.yield_dict[interaction_model])

        self.nspec = len(self.projectiles)
        self.yields = self.yield_dict[interaction_model]
        self.iam = interaction_model
        self.charm_model = None

    def is_yield(self, projectile, daughter):
        """Checks if a non-zero yield matrix exist for ``projectile``-
        ``daughter`` combination

        Args:
          projectile (int): PDG ID of projectile particle
          daughter (int): PDG ID of final state daughter/secondary particle
        Returns:
          bool: ``True`` if non-zero interaction matrix exists else ``False`` 
        """
        if projectile in self.projectiles and \
           daughter in self.secondary_dict[projectile]:
            return True
        else:
            if dbg > 1:
                print ('InteractionYields::is_yield(): no interaction matrix ' +
                       "for {0}, {1}->{2}".format(self.iam, projectile, daughter))
            return False

        return True

    def get_y_matrix(self, projectile, daughter):
        """Returns a ``DIM x DIM`` yield matrix.

        Args:
          projectile (int): PDG ID of projectile particle
          daughter (int): PDG ID of final state daughter/secondary particle
        Returns:
          numpy.array: yield matrix

        Note:
          In the current version, the matrices have to be multiplied by the 
          bin widths. In later versions they will be stored with the multiplication
          carried out. 
        """
        # TODO: modify yields to include the bin size
        return self.yields[(projectile, daughter)].dot(self.weights)

    def assign_yield_idx(self, projectile, projidx,
                         daughter, dtridx, cmat):
        """Copies a subset, defined in tuples ``projidx`` and ``dtridx`` from
        the ``yield_matrix(projectile,daughter)`` into ``cmat``

        Args:
          projectile (int): PDG ID of projectile particle
          projidx (int,int): tuple containing index range relative 
                             to the projectile's energy grid
          daughter (int): PDG ID of final state daughter/secondary particle
          dtridx (int,int): tuple containing index range relative 
                            to the daughters's energy grid
          cmat (numpy.array): array reference to the interaction matrix 
        """
        cmat[dtridx[0]:dtridx[1], projidx[0]:projidx[1]] = \
            self.get_y_matrix(projectile, daughter)[dtridx[0]:dtridx[1],
                                                    projidx[0]:projidx[1]]

    def inject_custom_charm_model(self, model='MRS'):
        """Overwrites the charm production yields of the yield 
        dictionary for the current interaction model with yields from 
        a custom model.

        The function walks through all (projectile, charm_daughter) 
        combinations and replaces the yield matrices with those from
        the ``model``.

        Args:
          model (str): charm model name

        Raises:
          NotImplementedError: if model string unknown.
        """

        from ParticleDataTool import SibyllParticleTable
        from charm_models import MRS_charm  # @UnresolvedImport

        if model == None:
            return

        if self.charm_model and self.charm_model != model:
            # reload the yields from the main dictionary
            self.set_interaction_model(self.iam, force=True)
#            raise Exception('InteractionYields:inject_custom_charm_model()::' +
#                            'changing injected charm model back to ' +
#                            'default not implemented .')

        sib = SibyllParticleTable()
        charm_modids = [sib.modid2pdg[modid] for modid in
                        sib.mod_ids if abs(modid) >= 59]
        del sib
        # make a copy of current yields before starting overwriting/injecting
        # a charm model on top
        from copy import copy
        self.yields = copy(self.yields)
        
        if model == 'MRS':
            
            # Set charm production to zero
            cs = HadAirCrossSections(self.iam)
            mrs = MRS_charm(self.e_grid, cs)
            for proj in self.projectiles:
                for chid in charm_modids:
                    self.yields[(proj, chid)] = mrs.get_yield_matrix(
                        proj, chid)

        elif model == 'sibyll23_pl':
            cs_h_air = HadAirCrossSections('SIBYLL2.3')
            cs_h_p = HadAirCrossSections('SIBYLL2.3_pp')
            for proj in self.projectiles:
                cs_scale = np.diag(cs_h_p.get_cs(proj)/cs_h_air.get_cs(proj))
                for chid in charm_modids:
                    # rescale yields with sigma_pp/sigma_air to ensure
                    # that in a later step indeed sigma_{pp,ccbar} is taken
                    
                    self.yields[(proj, chid)] = self.yield_dict[
                        'SIBYLL2.3_rc1_pl'][(proj, chid)].dot(cs_scale) * 14.5

        else:
            raise NotImplementedError('InteractionYields:inject_custom_charm_model()::' +
                                      ' Unsupported model')

        self._gen_index(self.yields)
        self.charm_model = model

    def __repr__(self):
        a_string = 'Possible (projectile,secondary) configurations:\n'
        for key in sorted(self.yields.keys()):
            if key not in ['evec', 'ebins']:
                a_string += str(key) + '\n'
        return a_string


class DecayYields():

    """Class for managing the dictionary of decay yield matrices.

    The class un-pickles a dictionary, which contains :math:`x` 
    spectra of decay products/daughters, sampled from PYTHIA 8 
    Monte Carlo.    

    Args:
      weights (numpy.array): bin widths of energy grid
    """

    def __init__(self, weights):
        self.weights = weights
        self._load()
        self._gen_index()

        self.particle_keys = self.mothers

    def _load(self):
        """Un-pickles the yields dictionary using the path specified as
        ``decay_fname`` in :mod:`mceq_config`.

        Raises:
          IOError: if file not found
        """
        import cPickle as pickle
        from os.path import join
        try:
            with open(join(config['data_dir'],
                           config['decay_fname']), 'r') as f:
                self.decay_dict = pickle.load(f)
        except IOError:
            self.decay_dict = _decompress(join(config['data_dir'],
                                            config['decay_fname']))
            # raise IOError('DecayYields::_load(): Yield file not found.')

    def _gen_index(self):
        """Generates index of mother-daughter relationships.

        This function is called once after un-pickling. In future 
        versions this index will be part of the pickled dictionary.
        """
        self.mothers = np.unique(zip(*self.decay_dict.keys())[0])
        self.daughter_dict = {}

        for mother in self.mothers:
            self.daughter_dict[mother] = []

        for key, mat in self.decay_dict.iteritems():
            mother, daughter = key
            if np.sum(mat) > 0:
                if daughter not in self.daughter_dict[mother]:
                    self.daughter_dict[mother].append(daughter)

        # special treatment for muons, which should decay even if they
        # have an alias ID
        # the ID 7313 not included, since it's "a copy of"
        for alias in [7013, 7113, 7213]:
            self.daughter_dict[alias] = self.daughter_dict[13]
            self.daughter_dict[-alias] = self.daughter_dict[-13]
            for d in self.daughter_dict[alias]:
                self.decay_dict[(alias, d)] = self.decay_dict[(13, d)]
            for d in self.daughter_dict[-alias]:
                self.decay_dict[(-alias, d)] = self.decay_dict[(-13, d)]

    def get_d_matrix(self, mother, daughter):
        """Returns a ``DIM x DIM`` decay matrix.

        Args:
          mother (int): PDG ID of mother particle
          daughter (int): PDG ID of final state daughter particle
        Returns:
          numpy.array: decay matrix

        Note:
          In the current version, the matrices have to be multiplied by the 
          bin widths. In later versions they will be stored with the multiplication
          carried out. 
        """
        if dbg > 1 and not self.is_daughter(mother, daughter):
            print ("DecayYields:get_d_matrix():: trying to get empty matrix" +
                   "{0} -> {1}").format(mother, daughter)
        # TODO: fix structure of the decay dict
        return (self.decay_dict[(mother, daughter)].T).dot(self.weights)

    def assign_d_idx(self, mother, moidx,
                     daughter, dtridx, dmat):
        """Copies a subset, defined in tuples ``moidx`` and ``dtridx`` from
        the ``decay_matrix(mother,daughter)`` into ``dmat``

        Args:
          mother (int): PDG ID of mother particle
          moidx (int,int): tuple containing index range relative 
                             to the mothers's energy grid
          daughter (int): PDG ID of final state daughter/secondary particle
          dtridx (int,int): tuple containing index range relative 
                            to the daughters's energy grid
          dmat (numpy.array): array reference to the decay matrix 
        """
        dmat[dtridx[0]:dtridx[1], moidx[0]:moidx[1]] = \
            self.get_d_matrix(mother, daughter)[dtridx[0]:dtridx[1],
                                                moidx[0]:moidx[1]]

    def is_daughter(self, mother, daughter):
        """Checks if ``daughter`` is a decay daughter of ``mother``.

        Args:
          mother (int): PDG ID of projectile particle
          daughter (int): PDG ID of daughter particle
        Returns:
          bool: ``True`` if ``daughter`` is daughter of ``mother`` 
        """
        if (mother not in self.daughter_dict.keys() or
                daughter not in self.daughter_dict[mother]):
            return False
        else:
            return True

    def daughters(self, mother):
        """Checks if ``mother`` decays and returns the list of daughter particles.

        Args:
          mother (int): PDG ID of projectile particle
        Returns:
          list: PDG IDs of daughter particles 
        """
        if mother not in self.daughter_dict.keys():
            if dbg > 2:
                print "DecayYields:daughters():: requesting daughter " + \
                    "list for stable or not existing mother: " + str(mother)
            return []
        return self.daughter_dict[mother]

    def __repr__(self):
        a_string = 'Possible (mother,daughter) configurations:\n'
        for key in sorted(self.decay_dict.keys()):
            a_string += str(key) + '\n'
        return a_string


class HadAirCrossSections():

    """Class for managing the dictionary of hadron-air cross-sections.

    The class unpickles a dictionary, which contains proton-air,
    pion-air and kaon-air cross-sections tabulated on the common 
    energy grid.

    Args:
      interaction_model (str): name of the interaction model
    """
    #: current interaction model name
    iam = None
    #: current energy grid
    egrid = None

    #: unit - :math:`\text{GeV} \cdot \text{fm}`
    GeVfm = 0.19732696312541853
    #: unit - :math:`\text{GeV} \cdot \text{cm}`
    GeVcm = GeVfm * 1e-13
    #: unit - :math:`\text{GeV}^2 \cdot \text{mbarn}`
    GeV2mbarn = 10.0 * GeVfm ** 2
    #: unit conversion - :math:`\text{mbarn} \to \text{cm}^2`
    mbarn2cm2 = GeVcm ** 2 / GeV2mbarn

    def __init__(self, interaction_model):

        self._load()

        if interaction_model != None:
            self.set_interaction_model(interaction_model)
        else:
            # Set some default interaction model to allow for cross-sections
            self.set_interaction_model('SIBYLL2.2')

    def _load(self):
        """Un-pickles a dictionary using the path specified as
        ``decay_fname`` in :mod:`mceq_config`.

        Raises:
          IOError: if file not found
        """
        import cPickle as pickle
        from os.path import join
        try:
            with open(join(config['data_dir'],
                           config['cs_fname']), 'r') as f:
                self.cs_dict = pickle.load(f)
        except IOError:
            self.cs_dict = _decompress(join(config['data_dir'],
                                            config['cs_fname']))
            # raise IOError('HadAirCrossSections::_load(): ' +
            #               'Yield file not found.')

        self.egrid = self.cs_dict['evec']

    def set_interaction_model(self, interaction_model):
        """Selects an interaction model and prepares all internal variables. 

        Args:
          interaction_model (str): interaction model name
        Raises:
          Exception: if invalid name specified in argument ``interaction_model``
        """
        if interaction_model == self.iam and dbg > 0:
            print ("InteractionYields:set_interaction_model():: Model " +
                   self.iam + " already loaded.")
            return

        if interaction_model in self.cs_dict.keys():
            self.iam = interaction_model
            
        elif interaction_model.find('SIBYLL2.2') == 0:
            if dbg > 1:
                print ("InteractionYields:set_interaction_model():: Model " +
                       interaction_model + " selected.")
            self.iam = 'SIBYLL2.3'
        
        elif interaction_model.find('SIBYLL2.3') == 0:
            self.iam = 'SIBYLL2.3'
        else:
            print "Available interaction models: ", self.cs_dict.keys()
            raise Exception("HadAirCrossSections(): No cross-sections for the desired " +
                            "interaction model {0} available.".format(interaction_model))
        self.cs = self.cs_dict[self.iam]

    def get_cs(self, projectile, mbarn=False):
        """Returns inelastic ``projectile``-air cross-section 
        :math:`\\sigma_{inel}^{proj-Air}(E)` as vector spanned over 
        the energy grid.

        Args:
          projectile (int): PDG ID of projectile particle
          mbarn (bool,optional): if ``True``, the units of the cross-section
                                 will be :math:`mbarn`, else :math:`\\text{cm}^2` 

        Returns:
          numpy.array: cross-section in :math:`mbarn` or :math:`\\text{cm}^2` 
        """

        message_templ = 'HadAirCrossSections(): replacing {0} with {1} cross-section'
        scale = 1.0

        if not mbarn:
            scale = self.mbarn2cm2

        if abs(projectile) in self.cs.keys():
            return scale * self.cs[projectile]
        elif abs(projectile) in [411, 421, 431, 15]:
            if dbg > 2:
                print message_templ.format('D', 'K+-')
            return scale * self.cs[321]
        elif abs(projectile) in [4332, 4232, 4132]:
            if dbg > 2:
                print message_templ.format('charmed baryon', 'nucleon')
            return scale * self.cs[2212]
        elif abs(projectile) > 2000 and abs(projectile) < 5000:
            if dbg > 2:
                print message_templ.format(projectile, 'nucleon')
            return scale * self.cs[2212]
        elif 11 < abs(projectile) < 17 or 7000 < abs(projectile) < 7500:
            if dbg > 2:
                print 'HadAirCrossSections(): returning 0 cross-section for lepton', projectile
            return 0.
        else:
            if dbg > 2:
                print message_templ.format(projectile, 'pion')
            return scale * self.cs[211]

    def __repr__(self):
        a_string = 'HadAirCrossSections() available for the projectiles: \n'
        for key in sorted(self.cs.keys()):
            a_string += str(key) + '\n'
        return a_string
