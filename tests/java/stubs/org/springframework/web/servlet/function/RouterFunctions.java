package org.springframework.web.servlet.function;

/** Stub di compilazione: org.springframework.web.servlet.function.RouterFunctions. */
public abstract class RouterFunctions {
    public static Builder route() { return null; }

    /** Stub del builder. */
    public interface Builder {
        Builder route(RequestPredicate predicate, HandlerFunction<ServerResponse> handlerFunction);
        RouterFunction<ServerResponse> build();
    }
}
