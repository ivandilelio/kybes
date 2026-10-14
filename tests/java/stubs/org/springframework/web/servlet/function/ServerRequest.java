package org.springframework.web.servlet.function;

/** Stub di compilazione: org.springframework.web.servlet.function.ServerRequest. */
public interface ServerRequest {
    org.springframework.http.HttpMethod method();
    java.net.URI uri();
    jakarta.servlet.http.HttpServletRequest servletRequest();

    static ServerRequest create(jakarta.servlet.http.HttpServletRequest request,
                                java.util.List<org.springframework.http.converter.HttpMessageConverter<?>> converters) { return null; }
}
