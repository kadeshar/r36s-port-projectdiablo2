/* Compile on Linux to verify the Python mapper's wire ABI against UAPI headers.
 * No input devices are opened and no events are injected.
 */
#include <linux/input.h>
#include <linux/uinput.h>
#include <stddef.h>
#include <stdio.h>
_Static_assert(sizeof(struct input_id) == 8, "input_id");
_Static_assert(sizeof(struct input_absinfo) == 24, "input_absinfo");
_Static_assert(sizeof(struct uinput_user_dev) == 1116, "uinput_user_dev");
_Static_assert(offsetof(struct uinput_user_dev, absmax) == 92, "absmax");
_Static_assert(offsetof(struct uinput_user_dev, absmin) == 348, "absmin");
_Static_assert(UI_DEV_CREATE == 0x5501, "UI_DEV_CREATE");
_Static_assert(UI_DEV_DESTROY == 0x5502, "UI_DEV_DESTROY");
_Static_assert(UI_SET_EVBIT == 0x40045564, "UI_SET_EVBIT");
_Static_assert(UI_SET_KEYBIT == 0x40045565, "UI_SET_KEYBIT");
_Static_assert(UI_SET_ABSBIT == 0x40045567, "UI_SET_ABSBIT");
_Static_assert(EVIOCGABS(ABS_X) == 0x80184540, "EVIOCGABS");
_Static_assert(BTN_A == 0x130 && BTN_B == 0x131, "face AB");
_Static_assert(BTN_X == 0x133 && BTN_Y == 0x134, "face XY");
_Static_assert(BTN_SELECT == 0x13a && BTN_START == 0x13b, "select/start");
_Static_assert(BTN_MODE == 0x13c && BTN_THUMBL == 0x13d && BTN_THUMBR == 0x13e, "mode/thumb");
int main(void) {
    printf("Linux input ABI OK: user_dev=%zu, input_id=%zu, absinfo=%zu, event=%zu\n",
           sizeof(struct uinput_user_dev), sizeof(struct input_id),
           sizeof(struct input_absinfo), sizeof(struct input_event));
    return 0;
}
