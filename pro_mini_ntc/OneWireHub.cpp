#include "OneWireHub.h"
#include "OneWireItem.h"

#include "platform.h"

OneWireHub::OneWireHub(const uint8_t pin)
{
    _error = Error::NO_ERROR;

    slave_count = 0;
    slave_selected = nullptr;

#if OVERDRIVE_ENABLE
    od_mode = false;
#endif

    for (uint8_t i = 0; i < ONEWIRESLAVE_LIMIT; ++i)
    {
        slave_list[i] = nullptr;
    }

    // prepare pin
    pin_bitMask = PIN_TO_BITMASK(pin);
    pin_baseReg = PIN_TO_BASEREG(pin);
    pinMode(pin, INPUT); // first port-access should by done by this FN, does more than DIRECT_MODE_....
    DIRECT_WRITE_LOW(pin_baseReg, pin_bitMask);

}


// attach a sensor to the hub
uint8_t OneWireHub::attach(OneWireItem &sensor)
{
    if (slave_count >= ONEWIRESLAVE_LIMIT) return 255; // hub is full

    // find position of next free storage-position
    uint8_t position = 255;
    for (uint8_t i = 0; i < ONEWIRESLAVE_LIMIT; ++i)
    {
        // check for already attached sensors
        if (slave_list[i] == &sensor)
        {
            return i;
        }
        // store position of first empty space
        if ((position>ONEWIRESLAVE_LIMIT) && (slave_list[i] == nullptr))
        {
            position = i;
        }
    }

    if (position == 255)
        return 255;

    slave_list[position] = &sensor;
    slave_count++;
    buildIDTree();
    return position;
}

bool    OneWireHub::detach(const OneWireItem &sensor)
{
    // find position of sensor
    uint8_t position = 255;
    for (uint8_t i = 0; i < ONEWIRESLAVE_LIMIT; ++i)
    {
        if (slave_list[i] == &sensor)
        {
            position = i;
            break;
        }
    }

    if (position != 255)    return detach(position);

    return false;
}

bool    OneWireHub::detach(const uint8_t slave_number)
{
    if (slave_list[slave_number] == nullptr)    return false;
    if (slave_count == 0)                       return false;
    if (slave_number >= ONEWIRESLAVE_LIMIT)     return false;

    slave_list[slave_number] = nullptr;
    slave_count--;
    buildIDTree();

    return true;
}


// just look through each bit of each ID and build a tree, so there are n=slaveCount decision-points
// trade-off: more online calculation, but @4Slave 16byte storage instead of 3*256 byte
uint8_t OneWireHub::getNrOfFirstBitSet(const mask_t mask) const
{
    mask_t _mask = mask;
    for (uint8_t i = 0; i < ONEWIRESLAVE_LIMIT; ++i)
    {
        if ((_mask & 1) != 0)  return i;
        _mask >>= 1;
    }
    return 0;
}

// return next not empty element in slave-list
uint8_t OneWireHub::getIndexOfNextSensorInList(const uint8_t index_start) const
{
    for (uint8_t i = index_start; i < ONEWIRE_TREE_SIZE; ++i)
    {
        if (slave_list[i] != nullptr)  return i;
    }
    return 0;
}

// gone through the address, store this result
uint8_t OneWireHub::getNrOfFirstFreeIDTreeElement(void) const
{
    for (uint8_t i = 0; i < ONEWIRE_TREE_SIZE; ++i)
    {
        if (idTree[i].id_position == 255) return i;
    }
    return 0;
}

// initial FN to build the ID-Tree
uint8_t OneWireHub::buildIDTree(void)
{
    mask_t mask_slaves = 0;
    mask_t bit_mask    = 0x01;

    // build mask
    for (uint8_t i = 0; i< ONEWIRESLAVE_LIMIT; ++i)
    {
        if (slave_list[i] != nullptr) mask_slaves |= bit_mask;
        bit_mask <<= 1;
    }

    for (uint8_t i = 0; i< ONEWIRE_TREE_SIZE; ++i)
    {
        idTree[i].id_position = 255;
    }

    // begin with root-element
    buildIDTree(0, mask_slaves); // goto branch

    return 0;
}

// returns the branch that this iteration has worked on
uint8_t OneWireHub::buildIDTree(uint8_t position_IDBit, const mask_t mask_slaves)
{
    if (mask_slaves == 0) return (255);

    while (position_IDBit < 64)
    {
        mask_t        mask_pos  { 0 };
        mask_t        mask_neg  { 0 };
        const uint8_t pos_byte  { static_cast<uint8_t>(position_IDBit >> 3) };
        const uint8_t mask_bit  { static_cast<uint8_t>(1 << (position_IDBit & 7)) };
        mask_t        mask_id   { 1 };

        // searchIDTree through all active slaves
        for (uint8_t id = 0; id < ONEWIRESLAVE_LIMIT; ++id)
        {
            if ((mask_slaves & mask_id) != 0)
            {
                // if slave is in mask differentiate the bitValue
                if ((slave_list[id]->ID[pos_byte] & mask_bit) != 0)
                    mask_pos |= mask_id;
                else
                    mask_neg |= mask_id;
            }
            mask_id <<= 1;
        }

        if ((mask_neg != 0) && (mask_pos != 0))
        {
            // there was found a junction
            const uint8_t active_element = getNrOfFirstFreeIDTreeElement();

            idTree[active_element].id_position     = position_IDBit;
            idTree[active_element].slave_selected  = getNrOfFirstBitSet(mask_slaves);
            position_IDBit++;
            idTree[active_element].got_one         = buildIDTree(position_IDBit, mask_pos);
            idTree[active_element].got_zero        = buildIDTree(position_IDBit, mask_neg);
            return active_element;
        }

        position_IDBit++;
    }

    // gone through the address, store this result
    uint8_t active_element = getNrOfFirstFreeIDTreeElement();

    idTree[active_element].id_position     = 128;
    idTree[active_element].slave_selected  = getNrOfFirstBitSet(mask_slaves);
    idTree[active_element].got_one         = 255;
    idTree[active_element].got_zero        = 255;

    return active_element;
}


bool OneWireHub::poll(void)
{
    _error = Error::NO_ERROR;

    while (true)
    {
        // this additional check prevents an infinite loop when calling this FN without sensors attached
        if (slave_count == 0)       return true;

        //Once reset is done, go to next step
        if (checkReset())           return false;

        // Reset is complete, tell the master we are present
        if (showPresence())         return false;

        //Now that the master should know we are here, we will get a command from the master
        if (recvAndProcessCmd())    return false;

        // on total success we want to start again, because the next reset could only be ~125 us away
        wdt_reset();
    }
}


bool OneWireHub::checkReset(void) // there is a specific high-time needed before a reset may occur -->  >120us
{
    static_assert(ONEWIRE_TIME_RESET_MIN[0] > (ONEWIRE_TIME_SLOT_MAX[0] + ONEWIRE_TIME_READ_MAX[0]), "Timings are wrong"); // last number should read: max(ONEWIRE_TIME_WRITE_ZERO,ONEWIRE_TIME_READ_MAX)
    static_assert(ONEWIRE_TIME_READ_MAX[0] > ONEWIRE_TIME_WRITE_ZERO[0] , "switch ONEWIRE_TIME_WRITE_ZERO with ONEWIRE_TIME_READ_MAX in checkReset(), because it is bigger (worst case)");
    static_assert(ONEWIRE_TIME_RESET_MAX[0] > ONEWIRE_TIME_RESET_MIN[0], "Timings are wrong");
#if OVERDRIVE_ENABLE
    static_assert(ONEWIRE_TIME_RESET_MIN[1] > (ONEWIRE_TIME_SLOT_MAX[1] + ONEWIRE_TIME_READ_MAX[1]), "Timings are wrong");
    static_assert(ONEWIRE_TIME_READ_MAX[1]  > ONEWIRE_TIME_WRITE_ZERO[1], "switch ONEWIRE_TIME_WRITE_ZERO with ONEWIRE_TIME_READ_MAX in checkReset(), because it is bigger (worst case)");
    static_assert(ONEWIRE_TIME_RESET_MAX[0] > ONEWIRE_TIME_RESET_MIN[1], "Timings are wrong");
#endif

    DIRECT_MODE_INPUT(pin_baseReg, pin_bitMask);

    // is entered if there are two resets within a given time (timeslot-detection can issue this skip)
    if (_error == Error::RESET_IN_PROGRESS)
    {
        _error = Error::NO_ERROR;
        if (waitLoopsWhilePinIs(ONEWIRE_TIME_RESET_MIN[od_mode] - ONEWIRE_TIME_SLOT_MAX[od_mode] - ONEWIRE_TIME_READ_MAX[od_mode], false) == 0) // last number should read: max(ONEWIRE_TIME_WRITE_ZERO,ONEWIRE_TIME_READ_MAX)
        {
#if OVERDRIVE_ENABLE
            const timeOW_t loops_remaining = waitLoopsWhilePinIs(ONEWIRE_TIME_RESET_MAX[0], false); // showPresence() wants to start at high, so wait for it
            if (od_mode && ((ONEWIRE_TIME_RESET_MAX[0] - ONEWIRE_TIME_RESET_MIN[od_mode]) > loops_remaining))
            {
                od_mode = false; // normal reset detected, so leave OD-Mode
            };
#else
            waitLoopsWhilePinIs(ONEWIRE_TIME_RESET_MAX[0], false); // showPresence() wants to start at high, so wait for it
#endif
            return false;
        }
    }

    if (!DIRECT_READ(pin_baseReg, pin_bitMask)) return true; // just leave if pin is Low, don't bother to wait, TODO: really needed?

    // wait for the bus to become low (master-controlled), since we are polling we don't know for how long it was zero
    if (waitLoopsWhilePinIs(ONEWIRE_TIME_RESET_TIMEOUT, true) == 0)
    {
        //_error = Error::WAIT_RESET_TIMEOUT;
        return true;
    }

    const timeOW_t loops_remaining = waitLoopsWhilePinIs(ONEWIRE_TIME_RESET_MAX[0], false);

    // wait for bus-release by master
    if (loops_remaining == 0)
    {
        _error = Error::VERY_LONG_RESET;
        return true;
    }

#if OVERDRIVE_ENABLE
    if (od_mode && ((ONEWIRE_TIME_RESET_MAX[0] - ONEWIRE_TIME_RESET_MIN[0]) > loops_remaining))
    {
        od_mode = false; // normal reset detected, so leave OD-Mode
    };
#endif

    // If the master pulled low for to short this will trigger an error
    //if (loops_remaining > (ONEWIRE_TIME_RESET_MAX[0] - ONEWIRE_TIME_RESET_MIN[od_mode])) _error = Error::VERY_SHORT_RESET; // could be activated again, like the error above, errorhandling is mature enough now

    return (loops_remaining > (ONEWIRE_TIME_RESET_MAX[0] - ONEWIRE_TIME_RESET_MIN[od_mode]));
}


bool OneWireHub::showPresence(void)
{
    static_assert(ONEWIRE_TIME_PRESENCE_MAX[0] > ONEWIRE_TIME_PRESENCE_MIN[0], "Timings are wrong");
#if OVERDRIVE_ENABLE
    static_assert(ONEWIRE_TIME_PRESENCE_MAX[1] > ONEWIRE_TIME_PRESENCE_MIN[1], "Timings are wrong");
#endif

    // Master will delay it's "Presence" check (bus-read)  after the reset
    waitLoopsWhilePinIs(ONEWIRE_TIME_PRESENCE_TIMEOUT, true); // no pinCheck demanded, but this additional check can cut waitTime

    // pull the bus low and hold it some time
    DIRECT_WRITE_LOW(pin_baseReg, pin_bitMask);
    DIRECT_MODE_OUTPUT(pin_baseReg, pin_bitMask);    // drive output low

    wait(ONEWIRE_TIME_PRESENCE_MIN[od_mode]); // stays till the end, because it drives the bus low itself

    DIRECT_MODE_INPUT(pin_baseReg, pin_bitMask);     // allow it to float

    // When the master or other slaves release the bus within a given time everything is fine
    if (waitLoopsWhilePinIs((ONEWIRE_TIME_PRESENCE_MAX[od_mode] - ONEWIRE_TIME_PRESENCE_MIN[od_mode]), false) == 0)
    {
        _error = Error::PRESENCE_LOW_ON_LINE;
        return true;
    }

    return false;
}

// note: this FN calls sendBit() & recvBit() but doesn't handle interrupts -> calling FN must do this
void OneWireHub::searchIDTree(void)
{
    uint8_t position_IDBit  = 0;
    uint8_t trigger_pos     = 0;
    uint8_t active_slave    = idTree[trigger_pos].slave_selected;
    uint8_t trigger_bit     = idTree[trigger_pos].id_position;

    noInterrupts();

    while (position_IDBit < 64)
    {
        // if junction is reached, act different
        if (position_IDBit == trigger_bit)
        {
            if (sendBit(false)) return;
            if (sendBit(false)) return;

            const bool bit_recv = recvBit();
            if (_error != Error::NO_ERROR)  return;

            // switch to next junction
            trigger_pos = bit_recv ? idTree[trigger_pos].got_one : idTree[trigger_pos].got_zero;

            active_slave = idTree[trigger_pos].slave_selected;

            trigger_bit = (trigger_pos == 255) ? uint8_t(255) : idTree[trigger_pos].id_position;
        }
        else
        {
            const uint8_t pos_byte = (position_IDBit >> 3);
            const uint8_t mask_bit = (static_cast<uint8_t>(1) << (position_IDBit & (7)));
            bool bit_send;

            if ((slave_list[active_slave]->ID[pos_byte] & mask_bit) != 0)
            {
                bit_send = true;
                if (sendBit(true))  return;
                if (sendBit(false)) return;
            }
            else
            {
                bit_send = false;
                if (sendBit(false)) return;
                if (sendBit(true))  return;
            }

            const bool bit_recv = recvBit();
            if (_error != Error::NO_ERROR)  return;

            if (bit_send != bit_recv)  return;
        }
        position_IDBit++;
    }

    interrupts();

    slave_selected = slave_list[active_slave];
}

bool OneWireHub::recvAndProcessCmd(void)
{
    uint8_t address[8], cmd;
    bool    flag = false;

    recv(&cmd);

    if (_error == Error::RESET_IN_PROGRESS) return false; // stay in poll()-loop and trigger another datastream-detection
    if (_error != Error::NO_ERROR)          return true;
    
    switch (cmd)
    {
        case 0xF0: // Search rom

            slave_selected = nullptr;
            searchIDTree();
            return false; // always trigger a re-init after searchIDTree

        case 0x69: // overdrive MATCH ROM

#if OVERDRIVE_ENABLE
            od_mode = true;
            waitLoopsWhilePinIs(ONEWIRE_TIME_READ_MAX[0], false);
#endif

        case 0x55: // MATCH ROM - Choose/Select ROM

            slave_selected = nullptr;

            if (recv(address, 8))
            {
                break;
            }

            for (uint8_t i = 0; i < ONEWIRESLAVE_LIMIT; ++i)
            {
                if (slave_list[i] == nullptr) continue;

                flag = true;
                for (uint8_t j = 0; j < 8; ++j)
                {
                    if (slave_list[i]->ID[j] != address[j])
                    {
                        flag = false;
                        break;
                    }
                }

                if (flag)
                {
                    slave_selected = slave_list[i];
                    break;
                }
            }

            if (!flag)
            {
                return true;
            }

            if (slave_selected != nullptr)
            {
                slave_selected->duty(this);
            }
            break;

        case 0x3C: // overdrive SKIP ROM

#if OVERDRIVE_ENABLE
            od_mode = true;
            waitLoopsWhilePinIs(ONEWIRE_TIME_READ_MAX[0], false);
#endif
        case 0xCC: // SKIP ROM

            // NOTE: If more than one slave is present on the bus,
            // and a read command is issued following the Skip ROM command,
            // data collision will occur on the bus as multiple slaves transmit simultaneously
            if ((slave_selected == nullptr) && (slave_count == 1))
            {
                slave_selected = slave_list[getIndexOfNextSensorInList()];
            }
            if (slave_selected != nullptr)
            {
                slave_selected->duty(this);
            }
            if (!startConvert) startConvert = true;
            break;
            
        case 0x0F: // OLD READ ROM

            // only usable when there is ONE slave on the bus --> continue to current readRom

        case 0x33: // READ ROM

            // only usable when there is ONE slave on the bus
            if ((slave_selected == nullptr) && (slave_count == 1))
            {
                slave_selected = slave_list[getIndexOfNextSensorInList()];
            }
            if (slave_selected != nullptr)
            {
                slave_selected->sendID(this);
            }
            return false;

        case 0xEC: // ALARM SEARCH

            // TODO: Alarm searchIDTree command, respond if flag is set
            // is like searchIDTree-rom, but only slaves with triggered alarm will appear
            break;

        case 0xA5: // RESUME COMMAND

            if (slave_selected == nullptr) return true;
            slave_selected->duty(this);
            break;

        default: // Unknown command

            _error = Error::INCORRECT_ONEWIRE_CMD;
            _error_cmd = cmd;
    }

    if (_error == Error::RESET_IN_PROGRESS) return false;

    return (_error != Error::NO_ERROR);
}


// info: check for errors after calling and break/return if possible, returns true if error is detected
// NOTE: if called separately you need to handle interrupts, should be disabled during this FN
bool OneWireHub::sendBit(const bool value)
{
    const bool writeZero = !value;

    // Wait for bus to rise HIGH, signaling end of last timeslot
    timeOW_t retries = ONEWIRE_TIME_SLOT_MAX[od_mode];
    while ((DIRECT_READ(pin_baseReg, pin_bitMask) == 0) && (--retries != 0));
    if (retries == 0)
    {
        _error = Error::RESET_IN_PROGRESS;
        return true;
    }

    // Wait for bus to fall LOW, start of new timeslot
    retries = ONEWIRE_TIME_MSG_HIGH_TIMEOUT;
    while ((DIRECT_READ(pin_baseReg, pin_bitMask) != 0) && (--retries != 0));
    if (retries == 0)
    {
        _error = Error::AWAIT_TIMESLOT_TIMEOUT_HIGH;
        return true;
    }

    // first difference to inner-loop of read()
    if (writeZero)
    {
        DIRECT_MODE_OUTPUT(pin_baseReg, pin_bitMask);
        retries = ONEWIRE_TIME_WRITE_ZERO[od_mode];
    }
    else
    {
        retries = ONEWIRE_TIME_READ_MAX[od_mode];
    }

    while ((DIRECT_READ(pin_baseReg, pin_bitMask) == 0) && (--retries != 0)); // TODO: we should check for (!retries) because there could be a reset in progress...
    DIRECT_MODE_INPUT(pin_baseReg, pin_bitMask);

    return false;
}


// should be the prefered function for writes, returns true if error occured
bool OneWireHub::send(const uint8_t address[], const uint8_t data_length)
{
    noInterrupts(); // will be enabled at the end of function
    DIRECT_WRITE_LOW(pin_baseReg, pin_bitMask);
    DIRECT_MODE_INPUT(pin_baseReg, pin_bitMask);
    uint8_t bytes_sent = 0;

    for ( ; bytes_sent < data_length; ++bytes_sent)             // loop for sending bytes
    {
        const uint8_t dataByte = address[bytes_sent];

        for (uint8_t bitMask = 0x01; bitMask != 0; bitMask <<= 1)    // loop for sending bits
        {
            if (sendBit(static_cast<bool>(bitMask & dataByte)))
            {
                if ((bitMask == 0x01) && (_error == Error::AWAIT_TIMESLOT_TIMEOUT_HIGH)) _error = Error::FIRST_BIT_OF_BYTE_TIMEOUT;
                interrupts();
                return true;
            }
        }
    }
    interrupts();
    return (bytes_sent != data_length);
}

bool OneWireHub::send(const uint8_t address[], const uint8_t data_length, uint16_t &crc16)
{
    noInterrupts(); // will be enabled at the end of function
    DIRECT_WRITE_LOW(pin_baseReg, pin_bitMask);
    DIRECT_MODE_INPUT(pin_baseReg, pin_bitMask);
    uint8_t bytes_sent = 0;

    for ( ; bytes_sent < data_length; ++bytes_sent)             // loop for sending bytes
    {
        uint8_t dataByte = address[bytes_sent];

        for (uint8_t counter = 0; counter < 8; ++counter)       // loop for sending bits
        {
            if (sendBit(static_cast<bool>(0x01 & dataByte)))
            {
                if ((counter == 0) && (_error ==Error::AWAIT_TIMESLOT_TIMEOUT_HIGH)) _error = Error::FIRST_BIT_OF_BYTE_TIMEOUT;
                interrupts();
                return true;
            }

            const uint8_t mix = ((uint8_t) crc16 ^ dataByte) & static_cast<uint8_t>(0x01);
            crc16 >>= 1;
            if (mix != 0)  crc16 ^= static_cast<uint16_t>(0xA001);
            dataByte >>= 1;
        }
    }
    interrupts();
    return (bytes_sent != data_length);
}

bool OneWireHub::send(const uint8_t dataByte)
{
    return send(&dataByte,1);
}

// NOTE: if called separately you need to handle interrupts, should be disabled during this FN
bool OneWireHub::recvBit(void)
{
    // Wait for bus to rise HIGH, signaling end of last timeslot
    timeOW_t retries = ONEWIRE_TIME_SLOT_MAX[od_mode];
    while ((DIRECT_READ(pin_baseReg, pin_bitMask) == 0) && (--retries != 0));
    if (retries == 0)
    {
        _error = Error::RESET_IN_PROGRESS;
        return true;
    }

    // Wait for bus to fall LOW, start of new timeslot
    retries = ONEWIRE_TIME_MSG_HIGH_TIMEOUT;
    while ((DIRECT_READ(pin_baseReg, pin_bitMask) != 0) && (--retries != 0));
    if (retries == 0)
    {
        _error = Error::AWAIT_TIMESLOT_TIMEOUT_HIGH;
        return true;
    }

    // wait a specific time to do a read (data is valid by then), // first difference to inner-loop of write()
    retries = ONEWIRE_TIME_READ_MIN[od_mode];
    while ((DIRECT_READ(pin_baseReg, pin_bitMask) == 0) && (--retries != 0));

    return (retries > 0);
}


bool OneWireHub::recv(uint8_t address[], const uint8_t data_length)
{
    noInterrupts(); // will be enabled at the end of function
    DIRECT_WRITE_LOW(pin_baseReg, pin_bitMask);
    DIRECT_MODE_INPUT(pin_baseReg, pin_bitMask);

    uint8_t bytes_received = 0;
    for ( ; bytes_received < data_length; ++bytes_received)
    {
        uint8_t value = 0;

        for (uint8_t bitMask = 0x01; bitMask != 0; bitMask <<= 1)
        {
            if (recvBit())                 value |= bitMask;
            if (_error != Error::NO_ERROR)
            {
                if ((bitMask == 0x01) && (_error ==Error::AWAIT_TIMESLOT_TIMEOUT_HIGH)) _error = Error::FIRST_BIT_OF_BYTE_TIMEOUT;
                interrupts();
                return true;
            }
        }

        address[bytes_received] = value;
        if (value == 0x44 && data_length == 1) startConvert = true;
    }

    interrupts();
    
    return (bytes_received != data_length);
}


// should be the prefered function for reads, returns true if error occured
bool OneWireHub::recv(uint8_t address[], const uint8_t data_length, uint16_t &crc16)
{
    noInterrupts(); // will be enabled at the end of function
    DIRECT_WRITE_LOW(pin_baseReg, pin_bitMask);
    DIRECT_MODE_INPUT(pin_baseReg, pin_bitMask);

    uint8_t bytes_received = 0;
    for ( ; bytes_received < data_length; ++bytes_received)
    {
        uint8_t value = 0;
        uint8_t mix = 0;
        for (uint8_t bitMask = 0x01; bitMask != 0; bitMask <<= 1)
        {
            if (recvBit())
            {
                value |= bitMask;
                mix = 1;
            }
            else mix = 0;

            if (_error != Error::NO_ERROR)
            {
                if ((bitMask == 0x01) && (_error ==Error::AWAIT_TIMESLOT_TIMEOUT_HIGH)) _error = Error::FIRST_BIT_OF_BYTE_TIMEOUT;
                interrupts();
                return true;
            }

            mix ^= static_cast<uint8_t>(crc16) & static_cast<uint8_t>(0x01);
            crc16 >>= 1;
            if (mix != 0)  crc16 ^= static_cast<uint16_t>(0xA001);
        }

        address[bytes_received] = value;
    }

    interrupts();
    return (bytes_received != data_length);
}


void OneWireHub::wait(const uint16_t timeout_us) const
{
    timeOW_t loops = timeUsToLoops(timeout_us);
    bool state = false;
    while (loops != 0)
    {
        loops = waitLoopsWhilePinIs(loops,state);
        state = !state;
    }
}

void OneWireHub::wait(const timeOW_t loops_wait) const
{
    timeOW_t loops = loops_wait;
    bool state = false;
    while (loops != 0)
    {
        loops = waitLoopsWhilePinIs(loops,state);
        state = !state;
    }
}

// returns false if pins stays in the wanted state all the time
timeOW_t OneWireHub::waitLoopsWhilePinIs(volatile timeOW_t retries, const bool pin_value) const
{
    if (retries == 0) return 0;
    while ((DIRECT_READ(pin_baseReg, pin_bitMask) == pin_value) && (--retries != 0));
    return retries;
}

void OneWireHub::raiseSlaveError(const uint8_t cmd)
{
    _error = Error::INCORRECT_SLAVE_USAGE;
    _error_cmd = cmd;
}

Error OneWireHub::clearError(void) // and return it if needed
{
    const Error _tmp = _error;
    _error = Error::NO_ERROR;
    return _tmp;
}

