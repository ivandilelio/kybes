package org.springframework.web.servlet.function;

/** Stub di compilazione: org.springframework.web.servlet.function.HandlerFunction. */
@FunctionalInterface
public interface HandlerFunction<T extends ServerResponse> {
    T handle(ServerRequest request) throws Exception;
}
