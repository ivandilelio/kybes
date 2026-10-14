package org.springframework.web.servlet.function;

/** Stub di compilazione: org.springframework.web.servlet.function.ServerResponse. */
public interface ServerResponse {
    org.springframework.http.HttpStatusCode statusCode();
    org.springframework.http.HttpHeaders headers();
    org.springframework.web.servlet.ModelAndView writeTo(jakarta.servlet.http.HttpServletRequest request,
            jakarta.servlet.http.HttpServletResponse response, Context context)
            throws jakarta.servlet.ServletException, java.io.IOException;

    static BodyBuilder status(int status) { return null; }

    /** Stub del builder della risposta. */
    interface BodyBuilder {
        BodyBuilder header(String headerName, String... headerValues);
        ServerResponse body(Object body);
        ServerResponse build();
    }

    /** Stub del contesto di scrittura. */
    interface Context {
        java.util.List<org.springframework.http.converter.HttpMessageConverter<?>> messageConverters();
    }
}
