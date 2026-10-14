package jakarta.servlet.http;

/** Stub di compilazione: jakarta.servlet.http.HttpServletRequest. */
public interface HttpServletRequest {
    java.util.Enumeration<String> getHeaderNames();
    java.util.Enumeration<String> getHeaders(String name);
    jakarta.servlet.ServletInputStream getInputStream() throws java.io.IOException;
}
