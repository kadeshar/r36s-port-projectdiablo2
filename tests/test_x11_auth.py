"""Private cookie-file tests; never start Xwayland or any ARM binary."""
import contextlib,importlib.util,os,pathlib,shutil,struct,tempfile,unittest,uuid
ROOT=pathlib.Path(__file__).resolve().parents[1];SCRIPTS=ROOT/'sdcard/ports/projectdiablo2/scripts'
spec=importlib.util.spec_from_file_location('x11_auth_test',SCRIPTS/'x11_auth.py');auth=importlib.util.module_from_spec(spec);spec.loader.exec_module(auth)
class X11AuthTests(unittest.TestCase):
 @contextlib.contextmanager
 def fixture(self):
  path=ROOT/'tests'/('x11-auth-fixture-'+uuid.uuid4().hex);path.mkdir()
  try:yield str(path)
  finally:shutil.rmtree(path)
 def test_records_are_bounded_same_cookie_and_no_stdout(self):
  with self.fixture() as d:
   path=pathlib.Path(d)/'xauthority';self.assertEqual(auth.create(path),None);data=path.read_bytes();self.assertLessEqual(len(data),auth.MAX_FILE)
   pos=0;cookies=[];families=[]
   while pos<len(data):
    family=struct.unpack_from('>H',data,pos)[0];pos+=2;fields=[]
    for _ in range(4):
     length=struct.unpack_from('>H',data,pos)[0];pos+=2;fields.append(data[pos:pos+length]);pos+=length
    families.append(family);cookies.append(fields[-1]);self.assertEqual(fields[1],b'0');self.assertEqual(fields[2],auth.NAME)
   self.assertEqual(families,[auth.FAMILY_WILD,auth.FAMILY_LOCAL]);self.assertEqual(cookies[0],cookies[1]);self.assertEqual(len(cookies[0]),16)
 def test_existing_target_and_wrong_name_fail_closed(self):
  with self.fixture() as d:
   path=pathlib.Path(d)/'xauthority';path.write_bytes(b'old')
   with self.assertRaises(ValueError):auth.create(path)
   with self.assertRaises(ValueError):auth.create(pathlib.Path(d)/'other')
 def test_cli_failure_is_silent(self):
  with self.fixture() as d:
   path=pathlib.Path(d)/'xauthority';self.assertEqual(auth.main(['--path',str(path)]),0);self.assertEqual(auth.main(['--path',str(path)]),1)
if __name__=='__main__':unittest.main()
