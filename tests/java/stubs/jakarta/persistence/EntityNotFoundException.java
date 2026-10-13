package jakarta.persistence;

public class EntityNotFoundException extends PersistenceException {
    private static final long serialVersionUID = 1L;

    public EntityNotFoundException(String message) { super(message); }
}
