"""
Calls the RDKit package.
"""

from qcelemental.models import Provenance, Result
from qcelemental.util import which_import

from .model import ProgramHarness
from ..exceptions import InputError
from ..units import ureg


class RDKitHarness(ProgramHarness):

    _defaults = {
        "name": "RDKit",
        "scratch": False,
        "thread_safe": True,
        "thread_parallel": False,
        "node_parallel": False,
        "managed_memory": False,
    }

    class Config(ProgramHarness.Config):
        pass

    @staticmethod
    def found(raise_error: bool=False) -> bool:
        return which_import('rdkit', return_bool=True, raise_error=raise_error, raise_msg='Please install via `conda install rdkit -c conda-forge`.')

    def compute(self, input_data: 'ResultInput', config: 'JobConfig') -> 'Result':
        """
        Runs RDKit in FF typing
        """

        self.found(raise_error=True)
        import rdkit
        from rdkit import Chem
        from rdkit.Chem import AllChem

        # Failure flag
        ret_data = {"success": False}

        # Build the Molecule
        jmol = input_data.molecule

        # Handle errors
        if abs(jmol.molecular_charge) > 1.e-6:
            raise InputError("RDKit does not currently support charged molecules.")

        if not jmol.connectivity:  # Check for empty list
            raise InputError("RDKit requires molecules to have a connectivity graph.")

        # Build out the base molecule
        base_mol = Chem.Mol()
        rw_mol = Chem.RWMol(base_mol)
        for sym in jmol.symbols:
            rw_mol.AddAtom(Chem.Atom(sym.title()))

        # Add in connectivity
        bond_types = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE, 3: Chem.BondType.TRIPLE}
        for atom1, atom2, bo in jmol.connectivity:
            rw_mol.AddBond(atom1, atom2, bond_types[bo])

        mol = rw_mol.GetMol()

        # Write out the conformer
        natom = len(jmol.symbols)
        conf = Chem.Conformer(natom)
        bohr2ang = ureg.conversion_factor("bohr", "angstrom")
        for line in range(natom):
            conf.SetAtomPosition(line, (bohr2ang * jmol.geometry[line, 0],
                                        bohr2ang * jmol.geometry[line, 1],
                                        bohr2ang * jmol.geometry[line, 2]))  # yapf: disable

        mol.AddConformer(conf)
        Chem.rdmolops.SanitizeMol(mol)

        if input_data.model.method.lower() == "uff":
            ff = AllChem.UFFGetMoleculeForceField(mol)
            all_params = AllChem.UFFHasAllMoleculeParams(mol)
        else:
            raise InputError("RDKit only supports the UFF method currently.")

        if all_params is False:
            raise InputError("RDKit parameters not found for all atom types in molecule.")

        ff.Initialize()

        ret_data["properties"] = {"return_energy": ff.CalcEnergy() * ureg.conversion_factor("kJ / mol", "hartree")}

        if input_data.driver == "energy":
            ret_data["return_result"] = ret_data["properties"]["return_energy"]
        elif input_data.driver == "gradient":
            coef = ureg.conversion_factor("kJ / mol", "hartree") * ureg.conversion_factor("angstrom", "bohr")
            ret_data["return_result"] = [x * coef for x in ff.CalcGrad()]
        else:
            raise InputError(f"RDKit can only compute energy and gradient driver methods. Found {input_data.driver}.")

        ret_data["provenance"] = Provenance(creator="rdkit",
                                            version=rdkit.__version__,
                                            routine="rdkit.Chem.AllChem.UFFGetMoleculeForceField")

        ret_data["schema_name"] = "qcschema_output"
        ret_data["success"] = True

        # Form up a dict first, then sent to BaseModel to avoid repeat kwargs which don't override each other
        return Result(**{**input_data.dict(), **ret_data})
