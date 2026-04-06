/*
 * Decompiled with CFR 0.152.
 */
import java.awt.Robot;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;

public class Main {
    public static void main(String[] stringArray) {
        Robot robot = null;
        try {
            System.out.println("Pressing (HOLD) key: two");
            robot = new Robot();
            robot.setAutoDelay(30);
            robot.keyPress(50);
            System.out.println("Done (key is now held down).");
            Files.write(Path.of(".ready", new String[0]), new byte[0], StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
            Thread.sleep(Long.MAX_VALUE);
        }
        catch (Throwable throwable) {
            System.out.println("Failed: " + String.valueOf(throwable));
            throwable.printStackTrace(System.out);
        }
        finally {
            if (robot != null) {
                try {
                    robot.keyRelease(50);
                    System.out.println("Released key on exit.");
                }
                catch (Throwable throwable) {
                    System.out.println("Failed to release key: " + String.valueOf(throwable));
                    throwable.printStackTrace(System.out);
                }
            }
        }
    }
}
