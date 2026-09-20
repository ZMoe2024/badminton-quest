package cn.badmintonquest.mobile;
import org.junit.Test;
import static org.junit.Assert.*;
public class HostsTest {
 @Test public void limitsSchoolAndImportOrigins(){
  assertTrue(Hosts.app(Hosts.SCHOOL+"/static/cas.html?ticket=test"));
  assertTrue(Hosts.website(Hosts.WEBSITE+"/"));
  assertTrue(Hosts.school("https://authserver.lzjtu.edu.cn/authserver/login"));
  for(String u:new String[]{"http://resm.lzjtu.edu.cn/","https://resm.lzjtu.edu.cn.evil.test/","https://resm.lzjtu.edu.cn@evil.test/","https://resm.lzjtu.edu.cn:444/","file:///etc/passwd","javascript:alert(1)"})assertFalse(u,Hosts.school(u));
  assertFalse(Hosts.website(Hosts.SCHOOL));
 }
}
