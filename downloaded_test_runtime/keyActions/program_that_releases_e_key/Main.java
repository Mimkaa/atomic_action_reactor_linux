/*
 * Decompiled with CFR 0.152.
 */
import java.awt.Robot;

public class Main {
    public static void main(String[] stringArray) {
        try {
            System.out.println("Releasing key: e");
            Robot robot = new Robot();
            robot.setAutoDelay(30);
            robot.keyRelease(69);
            System.out.println("Done (key released).");
        }
        catch (Throwable throwable) {
            System.out.println("Failed: " + String.valueOf(throwable));
            throwable.printStackTrace(System.out);
            System.exit(1);
        }
    }
}
