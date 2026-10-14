package org.springframework.web.servlet.function;

/** Stub di compilazione: org.springframework.web.servlet.function.RouterFunction. */
@FunctionalInterface
public interface RouterFunction<T extends ServerResponse> {
    java.util.Optional<HandlerFunction<T>> route(ServerRequest request);
}
