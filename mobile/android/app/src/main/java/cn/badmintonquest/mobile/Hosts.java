package cn.badmintonquest.mobile;
import java.net.URI;
public final class Hosts {
    public static final String WEBSITE="https://web-production-a9ba5b.up.railway.app";
    public static final String SCHOOL="https://resm.lzjtu.edu.cn";
    private static String host(String value) {
        try { URI u=new URI(value);return "https".equals(u.getScheme())&&u.getUserInfo()==null&&(u.getPort()==-1||u.getPort()==443)?u.getHost():null; }
        catch(Exception ignored){return null;}
    }
    public static boolean website(String value){return "web-production-a9ba5b.up.railway.app".equals(host(value));}
    public static boolean app(String value){return "resm.lzjtu.edu.cn".equals(host(value));}
    public static boolean school(String value){
        String h=host(value);return "resm.lzjtu.edu.cn".equals(h)||"authserver.lzjtu.edu.cn".equals(h)||
            "open.weixin.qq.com".equals(h)||"long.open.weixin.qq.com".equals(h);
    }
}
