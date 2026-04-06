import java.awt.Robot;
import java.awt.event.KeyEvent;

public class Main {
    public static void main(String[] args) {
        try {
            Robot robot = new Robot();
            robot.setAutoDelay(20);

            System.out.println("Pressing 'c' key in 500ms...");
            Thread.sleep(500);

            robot.keyPress(KeyEvent.VK_C);
            System.out.println("C DOWN");

            Thread.sleep(200);

            robot.keyRelease(KeyEvent.VK_C);
            System.out.println("C UP");

            Thread.sleep(200);

            System.out.println("Done.");
        } catch (Throwable t) {
            t.printStackTrace();
        }
    }
}
