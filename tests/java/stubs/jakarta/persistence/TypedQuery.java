package jakarta.persistence;
public interface TypedQuery<X> { java.util.List<X> getResultList(); default java.util.stream.Stream<X> getResultStream() { return getResultList().stream(); } X getSingleResult(); TypedQuery<X> setMaxResults(int m); TypedQuery<X> setFirstResult(int p); TypedQuery<X> setParameter(String name, Object value); }
