package org.springframework.mock.web;

/** Stub di compilazione: org.springframework.mock.web.MockHttpServletRequest. */
public class MockHttpServletRequest implements jakarta.servlet.http.HttpServletRequest {
    public MockHttpServletRequest(String method, String requestUri) { }
    public void setQueryString(String queryString) { }
    public void addHeader(String name, Object value) { }
    public void setContent(byte[] content) { }
    public void setContentType(String contentType) { }
    public java.util.Enumeration<String> getHeaderNames() { return null; }
    public java.util.Enumeration<String> getHeaders(String name) { return null; }
    public jakarta.servlet.ServletInputStream getInputStream() { return null; }
}
