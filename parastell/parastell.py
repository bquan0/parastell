import argparse
import yaml
from pathlib import Path

import cubit
import src.pystell.read_vmec as read_vmec

from . import log

from . import invessel_build as ivb
from . import magnet_coils as mc
from . import source_mesh as sm
from . import cubit_io as cubit_io
from .utils import m2cm


def make_material_block(mat_tag, block_id, vol_id_str):
    """Issue commands to make a material block using Cubit's
    native capabilities.
    
    Arguments:
       mat_tag (str) : name of material block
       block_id (int) : block number
       vol_id_str (str) : space-separated list of volume ids
    """

    cubit.cmd(
        f'create material "{mat_tag}" property_group '
        '"CUBIT-ABAQUS"'
    )
    cubit.cmd(
        f'block {block_id} add volume {vol_id_str}'
    )
    cubit.cmd(
        f'block {block_id} material \'{mat_tag}\''
    )

class Stellarator(object):
    """Parametrically generates a fusion stellarator reactor core model using
    plasma equilibrium data and user-defined parameters. In-vessel component
    geometries are determined by plasma equilibrium VMEC data and a
    user-defined, three-dimensional radial build, in which thickness values for
    each component are supplied in a grid defined by toroidal and poloidal
    angles. Magnets are defined by coil filament point-locus data and a
    user-defined cross-section. Source meshes are defined on plasma equilibrium
    VMEC data and a structured, uniform grid in magnetic flux space.

    Arguments:
        vmec_file (str): path to plasma equilibrium VMEC file.
        logger (object): logger object (defaults to None). If no logger is
            supplied, a default logger will be instantiated.
    """

    def __init__(
            self,
            vmec_file,
            logger=None
    ):
        
        self.logger = logger
        self.vmec_file = vmec_file

        self.vmec = read_vmec.VMECData(self.vmec_file)

        self.invessel_build = None
        self.magnet_set = None
        self.source_mesh = None

    @property
    def vmec_file(self):
        return self._vmec_file
    
    @vmec_file.setter
    def vmec_file(self, file):
        self._vmec_file = file
        if Path(self._vmec_file).suffix != '.nc':
            e = AssertionError(
                'Plasma equilibrium VMEC data file input has extension '
                f'\'{Path(self._vmec_file).suffix}\'. File format must be '
                'netCDF (\'.nc\').'
            )
            self._logger.error(e.args[0])
            raise e

    @property
    def logger(self):
        return self._logger
    
    @logger.setter
    def logger(self, logger_object):
        self._logger = logger_object
        if self._logger == None or not self._logger.hasHandlers():
            self._logger = log.init()

    def set_invessel_build_dict(self, invessel_build):
        """Sets in-vessel build dictionary, using default values for keys not
        defined by user.
        """
        invessel_build_def = {
            'repeat': 0,
            'num_ribs': 61,
            'num_rib_pts': 61,
            'scale': m2cm,
            'export_cad_to_dagmc': False,
            'plasma_mat_tag': None,
            'sol_mat_tag': None,
            'dagmc_filename': 'dagmc',
            'export_dir': ''
        }
        self.ivb_dict = invessel_build_def.copy()
        self.ivb_dict.update(invessel_build)

    def get_invessel_build_dict(self):
        """Returns in-vessel build dictionary.
        """
        return self.ivb_dict

    def construct_invessel_build(self, invessel_build):
        """Construct InVesselBuild class object.

        Arguments:
            invessel_build (dict): dictionary of in-vessel component
                parameters, including
                {
                    'toroidal_angles': toroidal angles at which radial build is
                        specified. This list should always begin at 0.0 and it
                        is advised not to extend beyond one stellarator period.
                        To build a geometry that extends beyond one period,
                        make use of the 'repeat' parameter [deg](array of
                        double).
                    'poloidal_angles': poloidal angles at which radial build is
                        specified. This array should always span 360 degrees
                        [deg](array of double).
                    'radial_build': dictionary representing the
                        three-dimensional radial build of in-vessel components,
                        including
                        {
                            'component': {
                                'thickness_matrix': 2-D matrix defining
                                    component thickness at (toroidal angle,
                                    poloidal angle) locations. Rows represent
                                    toroidal angles, columns represent poloidal
                                    angles, and each must be in the same order
                                    provided in toroidal_angles and
                                    poloidal_angles [cm](ndarray(double)).
                                'mat_tag': DAGMC material tag for component in
                                    DAGMC neutronics model (str, defaults to
                                    None). If none is supplied, the 'component'
                                    key will be used.
                            }
                        }.
                    'wall_s': closed flux surface label extrapolation at wall
                        (double).
                    'repeat': number of times to repeat build segment for full
                        model (int, defaults to 0).
                    'num_ribs': total number of ribs over which to loft for each
                        build segment (int, defaults to 61). Ribs are set at
                        toroidal angles interpolated between those specified in
                        'toroidal_angles' if this value is greater than the
                        number of entries in 'toroidal_angles'.
                    'num_rib_pts': total number of points defining each rib
                        spline (int, defaults to 61). Points are set at
                        poloidal angles interpolated between those specified in
                        'poloidal_angles' if this value is greater than the
                        number of entries in 'poloidal_angles'.
                    'scale': a scaling factor between the units of VMEC and [cm]
                        (double, defaults to m2cm = 100).
                    'export_cad_to_dagmc': export DAGMC neutronics H5M file of
                        in-vessel components via CAD-to-DAGMC (bool, defaults
                        to False).
                    'plasma_mat_tag': alternate DAGMC material tag to use for
                        plasma. If none is supplied, 'plasma' will be used
                        (str, defaults to None).
                    'sol_mat_tag': alternate DAGMC material tag to use for
                        scrape-off layer. If none is supplied, 'sol' will be
                        used (str, defaults to None).
                    'dagmc_filename': name of DAGMC output file, excluding
                        '.h5m' extension (str, defaults to 'dagmc').
                    'export_dir': directory to which to export the output files
                        (str, defaults to empty string).
                }
        """
        self.set_invessel_build_dict(invessel_build)
        ivb_dict = self.get_invessel_build_dict()

        self.invessel_build = ivb.InVesselBuild(
            self.vmec, ivb_dict['toroidal_angles'],
            ivb_dict['poloidal_angles'], ivb_dict['radial_build'],
            ivb_dict['wall_s'], repeat=ivb_dict['repeat'],
            num_ribs=ivb_dict['num_ribs'], num_rib_pts=ivb_dict['num_rib_pts'],
            scale=ivb_dict['scale'], plasma_mat_tag=ivb_dict['plasma_mat_tag'],
            sol_mat_tag=ivb_dict['sol_mat_tag'], logger=self.logger
        )

        self.invessel_build.populate_surfaces()
        self.invessel_build.calculate_loci()
        self.invessel_build.generate_components()

    def export_invessel_build(self, invessel_build):
        """Export Invessel Build components

        Arguments:
            invessel_build (dict): dictionary of in-vessel component
                parameters - see construct_invessel_build()
        """
        self.set_invessel_build_dict(invessel_build)
        ivb_dict = self.get_invessel_build_dict()
        
        self.invessel_build.export_step(export_dir=ivb_dict['export_dir'])

        if ivb_dict['export_cad_to_dagmc']:
            self.invessel_build.export_cad_to_dagmc(
                filename=ivb_dict['dagmc_filename'],
                export_dir=ivb_dict['export_dir']
            )

    def set_magnets_dict(self, magnets):
        """Sets magnets dictionary, using default values for keys not defined
        by user.
        """
        magnets_def = {
            'sample_mod': 1,
            'scale': m2cm,
            'step_filename': 'magnets',
            'mat_tag': 'magnets',
            'export_mesh': False,
            'mesh_filename': 'magnet_mesh',
            'export_dir': ''
        }
        self.magnets_dict = magnets_def.copy()
        self.magnets_dict.update(magnets)

    def get_magnets_dict(self):
        """Returns magnets dictionary.
        """
        return self.magnets_dict
    
    def construct_magnets(self, magnets):
        """Constructs MagnetSet class object.

        Arguments:
            magnets (dict): dictionary of magnet parameters, including
                {
                    'coils_file_path': path to coil filament data file (str).
                    'start_line': starting line index for data in file (int).
                    'cross_section': coil cross-section definition; see details
                        below (list).
                    'toroidal_extent': toroidal extent of magnets to model [deg]
                        (double).
                    'sample_mod': sampling modifier for filament points (int,
                        defaults to 1). For a user-supplied value of n, sample
                        every n points in list of points in each filament.
                    'scale': a scaling factor between the units of the filament
                        data and [cm] (double, defaults to m2cm = 100).
                    'step_filename': name of STEP export output file, excluding
                        '.step' extension (str, defaults to 'magnets').
                    'mat_tag': DAGMC material tag for magnets in DAGMC
                        neutronics model (str, defaults to 'magnets').
                    'export_mesh': flag to indicate tetrahedral mesh generation
                        for magnet volumes (bool, defaults to False).
                    'mesh_filename': name of tetrahedral mesh H5M file,
                        excluding '.h5m' extension (str, defaults to
                        'magnet_mesh').
                    'export_dir': directory to which to export output files
                        (str, defaults to empty string).
                }
                For the list defining the coil cross-section, the cross-section
                shape must be either a circle or rectangle. For a circular
                cross-section, the list format is
                ['circle' (str), radius [cm](double)]
                For a rectangular cross-section, the list format is
                ['rectangle' (str), width [cm](double), thickness [cm](double)]
        """
        self.set_magnets_dict(magnets)
        magnets_dict = self.get_magnets_dict()

        self.magnet_set = mc.MagnetSet(
            magnets_dict['coils_file_path'], magnets_dict['start_line'],
            magnets_dict['cross_section'], magnets_dict['toroidal_extent'],
            sample_mod=magnets_dict['sample_mod'], scale=magnets_dict['scale'],
            mat_tag=magnets_dict['mat_tag'], logger=self.logger
        )

        self.magnet_set.build_magnet_coils()

    def export_magnets(self, magnets):
        """Export magnet components

        Arguments:
            magnets (dict): dictionary of magnet component
                parameters - see construct_magnets()
        """
        self.set_magnets_dict(magnets)
        magnets_dict = self.get_magnets_dict()

        self.magnet_set.export_step(
            filename=magnets_dict['step_filename'],
            export_dir=magnets_dict['export_dir']
        )

        if magnets_dict['export_mesh']:
            self.magnet_set.mesh_magnets()
            self.magnet_set.export_mesh(
                filename=magnets_dict['mesh_filename'],
                export_dir=magnets_dict['export_dir']
            )

    def set_source_dict(self, source):
        """Sets source dictionary, using default values for keys not defined
        by user.
        """
        source_def = {
            'scale': m2cm,
            'filename': 'source_mesh',
            'export_dir': ''
        }
        self.source_dict = source_def.copy()
        self.source_dict.update(source)

    def get_source_dict(self):
        """Returns source dictionary.
        """
        return self.source_dict
    
    def construct_source_mesh(self, source):
        """Constructs SourceMesh class object.

        Arguments:
            source_dict (dict): dictionary of source mesh parameters including
                {
                    'num_s': number of closed flux surfaces for vertex
                        locations in each toroidal plane (int).
                    'num_theta': number of poloidal angles for vertex locations
                        in each toroidal plane (int).
                    'num_phi': number of toroidal angles for planes of vertices
                        (int).
                    'toroidal_extent': toroidal extent of source to model [deg]
                        (double).
                    'scale': a scaling factor between the units of VMEC and [cm]
                        (double, defaults to m2cm = 100).
                    'filename': name of H5M output file, excluding '.h5m'
                        extension (str, defaults to 'source_mesh').
                    'export_dir': directory to which to export H5M output file
                        (str, defaults to empty string).
                }
        """
        self.set_source_dict(source)
        source_dict = self.get_source_dict()

        self.source_mesh = sm.SourceMesh(
            self.vmec, source_dict['num_s'], source_dict['num_theta'],
            source_dict['num_phi'], source_dict['toroidal_extent'],
            scale=source_dict['scale'], logger=self.logger
        )

        self.source_mesh.create_vertices()
        self.source_mesh.create_mesh()

    def export_source_mesh(self, source):
        """Export source mesh

        Arguments:
            source (dict): dictionary of source mesh parameters
                see construct_source_mesh()
        """
        self.set_source_dict(source)
        source_dict = self.get_source_dict()

        self.source_mesh.export_mesh(
            filename=source_dict['filename'],
            export_dir=source_dict['export_dir']
        )

    def _import_ivb_step(self):
        """Imports STEP files from in-vessel build into Coreform Cubit.
        (Internal function not intended to be called externally)
        """
        for name, data in self.invessel_build.radial_build.items():
            vol_id = cubit_io.import_step_cubit(
                name, self.invessel_build.export_dir
            )
            data['vol_id'] = vol_id

    def _tag_materials_legacy(self):
        """Applies material tags to corresponding CAD volumes for legacy DAGMC
        neutronics model export.
        (Internal function not intended to be called externally)
        """
        if self.magnet_set:
            vol_id_str = " ".join(str(i) for i in list(self.magnet_set.volume_ids))
            cubit.cmd(
                f'group "mat:{self.magnet_set.mat_tag}" add volume {vol_id_str}'
            )

        if self.invessel_build:
            for data in self.invessel_build.radial_build.values():
                cubit.cmd(
                    f'group "mat:{data["mat_tag"]}" add volume {data["vol_id"]}'
                )

    def _tag_materials_native(self):
        """Applies material tags to corresponding CAD volumes for native DAGMC
        neutronics model export.
        (Internal function not intended to be called externally)
        """
        cubit.cmd('set duplicate block elements off')

        if self.magnet_set:
            vol_list = list(self.magnet_set.volume_ids)
            block_id = min(vol_list)
            vol_id_str = " ".join(str(i) for i in vol_list)
            make_material_block(self.magnet_set.mat_tag, block_id, vol_id_str)
        
        if self.invessel_build:
            for data in self.invessel_build.radial_build.values():
                block_id = data['vol_id']
                vol_id_str = str(block_id)
                make_material_block(data['mat_tag'], block_id, vol_id_str)

    def set_dagmc_export(self, dagmc_export):
        """Sets the DAGMC export dictionary, using default values for keys not
        defined by user.
        """
        dagmc_export_def = {
            'skip_imprint': False,
            'legacy_faceting': True,
            'faceting_tolerance': None,
            'length_tolerance': None,
            'normal_tolerance': None,
            'anisotropic_ratio': 100,
            'deviation_angle': 5,
            'filename': 'dagmc',
            'export_dir': ''
        }
        self.dagmc_export = dagmc_export_def.copy()
        self.dagmc_export.update(dagmc_export)

    def get_dagmc_export(self):
        """Returns DAGMC export dictionary.
        """
        return self.dagmc_export
    
    def export_dagmc(self, dagmc_export={}):
        """Exports DAGMC neutronics H5M file of ParaStell components via
        Coreform Cubit.

        Arguments:
            dagmc_export (dict): dictionary of DAGMC export parameters including
                {
                    'skip_imprint': choose whether to imprint and merge all in
                        Coreform Cubit or to merge surfaces based on import
                        order and geometry information (bool, defaults to
                        False).
                    'legacy_faceting': choose legacy or native faceting for
                        DAGMC export (bool, defaults to True).
                    'faceting_tolerance': maximum distance a facet may
                        be from surface of CAD representation for DAGMC export
                        (double, defaults to None).
                    'length_tolerance': maximum length of facet edge for DAGMC
                        export (double, defaults to None).
                    'normal_tolerance': maximum change in angle between normal
                        vector of adjacent facets (double, defaults to None).
                    'anisotropic_ratio': controls edge length ratio of elements
                        (double, defaults to 100.0).
                    'deviation_angle': controls deviation angle of facet from
                        surface (i.e., lesser deviation angle results in more
                        elements in areas with greater curvature) (double,
                        defaults to 5.0).
                    'filename': name of DAGMC output file, excluding '.h5m'
                        extension (str, defaults to 'dagmc').
                    'export_dir': directory to which to export DAGMC output file
                        (str, defaults to empty string).
                }
        """
        cubit_io.init_cubit()
        
        self.logger.info(
            'Exporting DAGMC neutronics model...'
        )

        self.set_dagmc_export(dagmc_export)
        export_dict = self.get_dagmc_export()

        if self.invessel_build:
            self._import_ivb_step()

        if export_dict['skip_imprint']:
            self.invessel_build.merge_layer_surfaces()
        else:
            cubit.cmd('imprint volume all')
            cubit.cmd('merge volume all')

        if export_dict['legacy_faceting']:
            self._tag_materials_legacy()
            cubit_io.export_dagmc_cubit_legacy(
                faceting_tolerance=export_dict['faceting_tolerance'],
                length_tolerance=export_dict['length_tolerance'],
                normal_tolerance=export_dict['normal_tolerance'],
                filename=export_dict['filename'],
                export_dir=export_dict['export_dir'],
            )
        else:
            self._tag_materials_native()
            cubit_io.export_dagmc_cubit_native(
                anisotropic_ratio=export_dict['anisotropic_ratio'],
                deviation_angle=export_dict['deviation_angle'],
                filename=export_dict['filename'],
                export_dir=export_dict['export_dir'],
            )


def parse_args():
    """Parser for running as a script.
    """
    parser = argparse.ArgumentParser(prog='stellarator')

    parser.add_argument(
        'filename',
        help='YAML file defining ParaStell stellarator configuration'
    )

    return parser.parse_args()


def read_yaml_config(filename):
    """Read YAML file describing the stellarator configuration and extract all
    data.
    """
    with open(filename) as yaml_file:
        all_data = yaml.safe_load(yaml_file)

    return (
        all_data['vmec_file'], all_data['invessel_build'],
        all_data['magnet_coils'], all_data['source_mesh'],
        all_data['dagmc_export']
    )


def parastell():
    """Main method when run as a command line script.
    """
    args = parse_args()

    (
        vmec_file, invessel_build, magnets, source, dagmc_export
    ) = read_yaml_config(args.filename)

    stellarator = Stellarator(vmec_file)

    # Invessel Build
    stellarator.construct_invessel_build(invessel_build)
    stellarator.export_invessel_build(invessel_build)

    # Magnets
    stellarator.construct_magnets(magnets)
    stellarator.export_magnets(magnets)

    # Source Mesh
    stellarator.construct_source_mesh(source)
    stellarator.export_source_mesh(source)
    
    # DAGMC export
    stellarator.export_dagmc(dagmc_export)


if __name__ == "__main__":
    parastell()
