package cn.badmintonquest.mobile;

import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import android.webkit.*;
import android.util.Base64;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import java.nio.charset.StandardCharsets;
import java.io.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class SchoolCookiesTest {
    private String script() throws Exception {
        try(InputStream stream=InstrumentationRegistry.getInstrumentation().getTargetContext().getAssets().open("collect.js")){
            ByteArrayOutputStream buffer=new ByteArrayOutputStream();byte[] chunk=new byte[4096];int n;
            while((n=stream.read(chunk))!=-1)buffer.write(chunk,0,n);
            return buffer.toString("UTF-8");
        }
    }
    private String evaluate(ActivityScenario<MainActivity> scenario,String expression)throws Exception{
        AtomicReference<String> value=new AtomicReference<>();CountDownLatch done=new CountDownLatch(1);
        scenario.onActivity(a->a.web.evaluateJavascript(expression,result->{value.set(result);done.countDown();}));
        assertTrue("JavaScript callback timed out",done.await(15,TimeUnit.SECONDS));return value.get();
    }
    private void page(ActivityScenario<MainActivity> scenario,String origin,String html)throws Exception{
        CountDownLatch ready=new CountDownLatch(1);
        scenario.onActivity(a->{a.web.stopLoading();a.web.setWebViewClient(new WebViewClient(){@Override public void onPageFinished(WebView view,String url){ready.countDown();}});a.web.loadDataWithBaseURL(origin,html,"text/html","UTF-8",null);});
        assertTrue("Fixture page did not load",ready.await(15,TimeUnit.SECONDS));
    }
    @Test public void extractsIdentityButHttpOnlyRequiresNativeCookieManager()throws Exception{
        try(ActivityScenario<MainActivity> scenario=ActivityScenario.launch(MainActivity.class)){
            String claims=Base64.encodeToString(("{\"username\":\"fixture\",\"exp\":"+(System.currentTimeMillis()/1000+600)+"}").getBytes(StandardCharsets.UTF_8),Base64.URL_SAFE|Base64.NO_WRAP|Base64.NO_PADDING);
            page(scenario,Hosts.SCHOOL+"/","<html><body>Local fixture only</body></html>");
            evaluate(scenario,"localStorage.setItem('currentUser',JSON.stringify({username:'fixture',userId:'fixture-id'}));localStorage.setItem('token','x."+claims+".x');true");
            CountDownLatch set=new CountDownLatch(1);
            scenario.onActivity(a->CookieManager.getInstance().setCookie(Hosts.SCHOOL+"/","evbSrBv8QGpBO=fixture; Path=/; Secure; HttpOnly",ok->set.countDown()));
            assertTrue(set.await(10,TimeUnit.SECONDS));
            assertFalse(evaluate(scenario,"document.cookie").contains("evbSrBv8QGpBO"));
            assertTrue(CookieManager.getInstance().getCookie(Hosts.SCHOOL+"/").contains("evbSrBv8QGpBO=fixture"));
            JSONObject result=new JSONObject(evaluate(scenario,script()));
            assertTrue(result.toString(),result.getBoolean("ok"));
            assertEquals("fixture",result.getJSONObject("currentUser").getString("username"));
            page(scenario,"https://untrusted.example/","<html><body>Other origin</body></html>");
            JSONObject blocked=new JSONObject(evaluate(scenario,script()));
            assertFalse(blocked.getBoolean("ok"));assertFalse(blocked.has("token"));
        }
    }
}
